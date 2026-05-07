import hashlib
import os
import shutil
import uuid
from collections import defaultdict
from datetime import datetime
from typing import List, Optional, Dict, Any

from fastapi import (
    BackgroundTasks, Depends, FastAPI, File, Form, HTTPException, UploadFile, status
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from pydantic import BaseModel
from sqlalchemy.orm import Session

import auth as auth_module
from auth import get_current_user, require_admin
from config import settings
from database import SessionLocal, engine, get_db
from document_processor import DocumentProcessor
from file_scanner import FileInfo, scan_directory
from models import Base, Document, Metadata, User
from search import SearchEngine
from vector_store import MilvusVectorStore, get_embedding, get_embeddings_batch, chunk_document

# Create all DB tables on startup
Base.metadata.create_all(bind=engine)
os.makedirs(settings.upload_dir, exist_ok=True)


def seed_default_users():
    """Ensure default admin and user accounts exist with the correct credentials."""
    defaults = [
        {"username": "admin", "email": "admin@example.com", "password": "admin",    "role": "admin"},
        {"username": "user",  "email": "user@example.com",  "password": "password", "role": "user"},
    ]
    db = SessionLocal()
    try:
        for d in defaults:
            existing = db.query(User).filter_by(username=d["username"]).first()
            if existing:
                # Always keep default accounts at their defined password and role
                existing.password_hash = auth_module.get_password_hash(d["password"])
                existing.role = d["role"]
            else:
                db.add(User(
                    username=d["username"],
                    email=d["email"],
                    password_hash=auth_module.get_password_hash(d["password"]),
                    role=d["role"],
                ))
                print(f"Created default {d['role']} account: {d['username']}")
        db.commit()
    finally:
        db.close()


seed_default_users()

app = FastAPI(title="Document Manager API", version="2.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:8002",
        "http://localhost:8003",
        "http://localhost:8004",
        "http://localhost:3000",
        "http://localhost:5173",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ── Pydantic schemas ──────────────────────────────────────────────────────────

class RegisterRequest(BaseModel):
    username: str
    email: str
    password: str
    role: str = "user"  # "admin" or "user"


class LoginRequest(BaseModel):
    username: str
    password: str


class UserResponse(BaseModel):
    id: str
    username: str
    email: str
    role: str


class TokenResponse(BaseModel):
    access_token: str
    token_type: str
    user: UserResponse


class DocumentResponse(BaseModel):
    id: str
    filename: str
    file_path: str
    file_type: str
    file_size: int
    status: str
    created_at: Optional[datetime]
    category: Optional[str] = None


class ScanRequest(BaseModel):
    directory: str


class SearchRequest(BaseModel):
    query: str
    file_type: Optional[str] = None
    language: Optional[str] = None
    limit: int = 20


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str


class SearchResult(BaseModel):
    id: str
    score: float
    filename: str
    file_path: str
    file_type: str
    snippet: str
    author: Optional[str]
    creation_date: Optional[datetime]
    page_count: int
    page_number: int = 1


class SearchResponse(BaseModel):
    total_results: int
    results: List[SearchResult]
    explanation: Optional[str] = None


class RagChatRequest(BaseModel):
    query: str
    max_context_tokens: int = 3000


class RagChatResponse(BaseModel):
    response: str
    sources: List[Dict[str, Any]]   # each has filename, id, score, page_number, excerpt
    total_sources: int


# ── Helpers ───────────────────────────────────────────────────────────────────

import re as _re

def find_page_for_query(file_path: str, query: str, stored_content: str = '') -> int:
    """Return the first 1-based page number where query words all appear.

    Uses word-level matching so 'AI deployment' finds a page containing
    both words even if they aren't adjacent (e.g. separated by '&').
    Prefers [PAGE_N] markers in stored_content; falls back to reading the PDF.
    """
    words = [w.lower() for w in query.split() if len(w) > 1]
    if not words:
        return 1

    def matches(text: str) -> bool:
        t = text.lower()
        return all(w in t for w in words)

    # Fast path: parse page markers from stored content
    if stored_content and '[PAGE_' in stored_content:
        parts = _re.split(r'\[PAGE_(\d+)\]\n?', stored_content)
        for i in range(1, len(parts), 2):
            try:
                page_num = int(parts[i])
                page_text = parts[i + 1] if i + 1 < len(parts) else ''
                if matches(page_text):
                    return page_num
            except (ValueError, IndexError):
                continue
        return 1

    # Slow path: read the PDF from disk
    try:
        import PyPDF2
        with open(file_path, 'rb') as f:
            reader = PyPDF2.PdfReader(f)
            for i, page in enumerate(reader.pages, 1):
                if matches(page.extract_text() or ''):
                    return i
    except Exception:
        pass
    return 1


def clean_snippet(text: str) -> str:
    """Strip [PAGE_N] markers and collapse excess whitespace from a snippet."""
    text = _re.sub(r'\[PAGE_\d+\]\n?', '', text)
    text = _re.sub(r'\n{3,}', '\n\n', text)
    return text.strip()


_OLLAMA_MODEL = settings.ollama_model   # use local open-source Ollama model by default


def _call_ollama(system_msg: str, user_msg: str, max_tokens: int = 400) -> str:
    """Call a local Ollama model via OpenAI-compatible API. Returns empty string on failure."""
    try:
        import openai
        client = openai.OpenAI(base_url=f"{settings.ollama_url}/v1", api_key="ollama")
        resp = client.chat.completions.create(
            model=_OLLAMA_MODEL,
            messages=[
                {"role": "system", "content": system_msg},
                {"role": "user",   "content": user_msg},
            ],
            temperature=0.2,
            max_tokens=max_tokens,
            timeout=30.0,
        )
        return resp.choices[0].message.content.strip()
    except Exception as e:
        print(f"Ollama ({_OLLAMA_MODEL}) call failed: {e}")
    return ""


def generate_search_explanation(query: str, results: list) -> str:
    """Use Ollama to produce a short explanation of what was found for a search query."""
    if not results:
        return ""
    snippets = []
    for r in results[:5]:
        snippet = clean_snippet(r.snippet or "")[:300]
        if snippet:
            snippets.append(f"From \"{r.filename}\" (page {r.page_number}): {snippet}")
    if not snippets:
        return ""
    context = "\n\n".join(snippets)
    user_msg = (
        f"The user searched for: \"{query}\"\n\n"
        f"The following content was found in the matching documents:\n\n{context}\n\n"
        f"In 2-3 sentences, explain what these documents contain about \"{query}\" "
        f"and what the user is likely to find in them."
    )
    return _call_ollama(
        "You are a concise document search assistant. Summarize what was found in the search results. Be brief and factual.",
        user_msg,
        max_tokens=180,
    )


# ── Auth endpoints ────────────────────────────────────────────────────────────

@app.post("/api/auth/register", response_model=UserResponse)
async def register(req: RegisterRequest, db: Session = Depends(get_db),
                   current_user: User = Depends(require_admin)):
    if req.role not in ("admin", "user"):
        raise HTTPException(status_code=400, detail="Role must be 'admin' or 'user'")

    if db.query(User).filter(User.username == req.username).first():
        raise HTTPException(status_code=400, detail="Username already taken")

    if db.query(User).filter(User.email == req.email).first():
        raise HTTPException(status_code=400, detail="Email already registered")

    user = User(
        username=req.username,
        email=req.email,
        password_hash=auth_module.get_password_hash(req.password),
        role=req.role,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    return UserResponse(
        id=str(user.id),
        username=user.username,
        email=user.email,
        role=user.role,
    )


@app.post("/api/auth/login", response_model=TokenResponse)
async def login(req: LoginRequest, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.username == req.username).first()
    if not user or not auth_module.verify_password(req.password, user.password_hash):
        raise HTTPException(status_code=401, detail="Invalid username or password")

    token = auth_module.create_access_token({"sub": str(user.id)})
    return TokenResponse(
        access_token=token,
        token_type="bearer",
        user=UserResponse(
            id=str(user.id),
            username=user.username,
            email=user.email,
            role=user.role,
        ),
    )


@app.get("/api/auth/me", response_model=UserResponse)
async def get_me(current_user: User = Depends(get_current_user)):
    return UserResponse(
        id=str(current_user.id),
        username=current_user.username,
        email=current_user.email,
        role=current_user.role,
    )


@app.post("/api/auth/change-password")
async def change_password(
    req: ChangePasswordRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if not auth_module.verify_password(req.current_password, current_user.password_hash):
        raise HTTPException(status_code=400, detail="Current password is incorrect")
    if len(req.new_password) < 4:
        raise HTTPException(status_code=400, detail="New password must be at least 4 characters")
    current_user.password_hash = auth_module.get_password_hash(req.new_password)
    db.commit()
    return {"message": "Password changed successfully"}


# ── Document endpoints ────────────────────────────────────────────────────────

@app.get("/api/documents", response_model=List[DocumentResponse])
async def get_documents(
    skip: int = 0,
    limit: int = 100,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    docs = db.query(Document).order_by(Document.created_at.desc()).offset(skip).limit(limit).all()
    return [
        DocumentResponse(
            id=str(doc.id),
            filename=doc.filename,
            file_path=doc.file_path,
            file_type=doc.file_type or "application/pdf",
            file_size=doc.file_size or 0,
            status=doc.status or "indexed",
            created_at=doc.created_at,
            category=doc.category,
        )
        for doc in docs
    ]


@app.post("/api/documents/upload")
async def upload_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    category: str = Form(None),
    current_user: User = Depends(require_admin),
):
    allowed_exts = ('.pdf', '.png', '.jpeg', '.jpg', '.doc', '.docx', '.xls', '.xlsx', '.csv')
    if not file.filename.lower().endswith(allowed_exts):
        raise HTTPException(status_code=400, detail="Unsupported file format")

    file_content = await file.read()

    # Save directly to permanent storage
    safe_filename = f"{uuid.uuid4()}_{file.filename}"
    file_path = os.path.join(settings.upload_dir, safe_filename)
    with open(file_path, "wb") as f:
        f.write(file_content)

    background_tasks.add_task(process_uploaded_file, file_path, file.filename, category)
    return {"message": "File uploaded successfully", "filename": file.filename}


def compress_pdf(file_path: str) -> None:
    """Rewrite the PDF with maximum stream compression to minimise stored size."""
    try:
        import pikepdf
        with pikepdf.open(file_path, allow_overwriting_input=True) as pdf:
            pdf.save(
                file_path,
                compress_streams=True,
                object_stream_mode=pikepdf.ObjectStreamMode.generate,
            )
    except Exception as e:
        print(f"PDF compression skipped for {file_path}: {e}")


def compress_image(file_path: str) -> None:
    try:
        from PIL import Image
        import os
        if os.path.getsize(file_path) > 2 * 1024 * 1024:
            with Image.open(file_path) as img:
                img.save(file_path, optimize=True, quality=85)
    except Exception as e:
        print(f"Image compression skipped for {file_path}: {e}")

def process_uploaded_file(file_path: str, original_filename: str, category: str = None):
    # Compress in place before hashing/storing if > 2MB
    file_ext = original_filename.lower().split('.')[-1]
    if file_ext == 'pdf':
        if os.path.getsize(file_path) > 2 * 1024 * 1024:
            compress_pdf(file_path)
    elif file_ext in ['png', 'jpg', 'jpeg']:
        compress_image(file_path)
    try:
        with open(file_path, "rb") as f:
            file_hash = hashlib.md5(f.read()).hexdigest()

        processor = DocumentProcessor()
        search_engine = SearchEngine()
        db: Session = SessionLocal()
        try:
            existing = db.query(Document).filter_by(file_hash=file_hash).first()
            if existing:
                # If the stored file is missing, update the path to the new copy
                if not os.path.exists(existing.file_path):
                    existing.file_path = file_path
                    db.commit()
                    print(f"Restored missing file for: {existing.filename}")
                else:
                    # Duplicate with healthy file — remove the redundant copy
                    try:
                        os.remove(file_path)
                    except Exception:
                        pass
                    print(f"Duplicate skipped: {original_filename}")
                return

            text = processor.extract_text(file_path)
            metadata = processor.extract_metadata(file_path)

            doc = Document(
                filename=original_filename,
                file_path=file_path,
                file_type=f"application/{file_ext}",
                file_size=os.path.getsize(file_path),
                file_hash=file_hash,
                content=text,
                category=category,
                status='indexed',
            )
            db.add(doc)
            db.flush()

            meta = Metadata(
                document_id=doc.id,
                author=metadata.get('author'),
                creation_date=metadata.get('creation_date'),
                language=metadata.get('language', 'en'),
                page_count=metadata.get('page_count', 1),
                custom_tags=metadata.get('custom_tags'),
            )
            db.add(meta)

            search_metadata = {
                'filename': original_filename,
                'file_path': file_path,
                'file_type': "application/pdf",
                'author': metadata.get('author'),
                'creation_date': metadata.get('creation_date'),
                'language': metadata.get('language', 'en'),
                'page_count': metadata.get('page_count', 1),
                'category': category,
            }
            try:
                search_engine.index_document(str(doc.id), text, search_metadata)
            except Exception as e:
                print(f"Elasticsearch indexing skipped: {e}")

            db.commit()
            print(f"Processed: {original_filename}")

            # ── Vector indexing (Milvus) ──────────────────────────────────────
            _embed_and_store(str(doc.id), original_filename, text)

        except Exception as e:
            db.rollback()
            print(f"Error processing {original_filename}: {e}")
        finally:
            db.close()
    except Exception as e:
        print(f"Fatal error in process_uploaded_file: {e}")


def _embed_and_store(doc_id: str, filename: str, content: str):
    """Chunk content, embed each chunk, and upsert into Milvus. Best-effort."""
    try:
        chunks = chunk_document(content)
        if not chunks:
            print(f"[Vector] No chunks produced for: {filename}")
            return
        vs = MilvusVectorStore()
        # Remove any previous vectors for this doc (handles re-upload)
        vs.delete_by_doc_id(doc_id)
        embedded = []
        for chunk in chunks:
            emb = get_embedding(chunk["content"])
            if emb:
                chunk["embedding"] = emb
                embedded.append(chunk)
        stored = vs.insert_chunks(doc_id, filename, embedded)
        print(f"[Vector] Stored {stored}/{len(chunks)} chunks for: {filename}")
    except Exception as e:
        print(f"[Vector] Indexing failed for {filename}: {e}")


@app.delete("/api/documents/{doc_id}")
async def delete_document(
    doc_id: str,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    # Remove from Elasticsearch index (best-effort)
    try:
        SearchEngine().delete_document(doc_id)
    except Exception:
        pass

    # Remove from Milvus vector store (best-effort)
    try:
        MilvusVectorStore().delete_by_doc_id(doc_id)
    except Exception:
        pass

    # Delete file from disk
    if doc.file_path and os.path.exists(doc.file_path):
        try:
            os.remove(doc.file_path)
        except Exception as e:
            print(f"Could not delete file {doc.file_path}: {e}")

    # Remove metadata and document records
    db.query(Metadata).filter(Metadata.document_id == doc.id).delete()
    db.delete(doc)
    db.commit()

    return {"message": "Document deleted successfully"}


@app.get("/api/documents/{doc_id}/file")
async def get_document_file(
    doc_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    if not doc.file_path or not os.path.exists(doc.file_path):
        raise HTTPException(status_code=404, detail="File not found on disk")

    return FileResponse(
        doc.file_path,
        media_type="application/pdf",
        filename=doc.filename,
    )


@app.get("/api/documents/{doc_id}/download")
async def download_document(
    doc_id: str,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    doc = db.query(Document).filter(Document.id == doc_id).first()
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    if not doc.file_path or not os.path.exists(doc.file_path):
        raise HTTPException(status_code=404, detail="File not found on disk")

    return FileResponse(
        doc.file_path,
        media_type="application/pdf",
        filename=doc.filename,
        headers={"Content-Disposition": f'attachment; filename="{doc.filename}"'},
    )


# ── Search endpoint ───────────────────────────────────────────────────────────

@app.post("/api/search", response_model=SearchResponse)
async def search_documents(
    search_request: SearchRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    q = search_request.query

    # Try Elasticsearch first, fall back to DB full-text search
    raw_results = None
    try:
        search_engine = SearchEngine()
        filters = {}
        if search_request.file_type:
            filters['file_type'] = search_request.file_type
        if search_request.language:
            filters['language'] = search_request.language
        raw_results = search_engine.search(query=q, filters=filters, limit=search_request.limit)
    except Exception as e:
        print(f"Elasticsearch unavailable, falling back to DB search: {e}")

    if raw_results is not None:
        all_hits = raw_results.get('results', [])

        # Keep only results that are at least 30% as relevant as the top hit
        if all_hits:
            max_score = max(r.get('score', 0) for r in all_hits) or 1.0
            min_score = max_score * 0.30
            all_hits = [r for r in all_hits if r.get('score', 0) >= min_score]

        # Enrich with page numbers — skip any ES entry whose ID is no longer in the DB
        enriched = []
        for r in all_hits:
            doc = db.query(Document).filter(Document.id == r['id']).first()
            if not doc:
                # Stale ES entry — remove it so it won't appear again
                try:
                    SearchEngine().delete_document(r['id'])
                except Exception:
                    pass
                continue
            page_num = find_page_for_query(
                doc.file_path or '', q, stored_content=doc.content or ''
            )
            raw_snippet = r.get('snippet', '')
            enriched.append(SearchResult(
                id=r['id'],
                score=r.get('score', 1.0),
                filename=r.get('filename', ''),
                file_path=r.get('file_path', ''),
                file_type=r.get('file_type', 'application/pdf'),
                snippet=clean_snippet(raw_snippet),
                author=r.get('author'),
                creation_date=r.get('creation_date'),
                page_count=r.get('page_count', 1),
                page_number=page_num,
            ))

        explanation = generate_search_explanation(q, enriched)
        return SearchResponse(
            total_results=len(enriched),
            results=enriched,
            explanation=explanation or None,
        )

    # DB fallback — search filename and content (content includes page markers)
    docs = (
        db.query(Document)
        .filter(
            (Document.content.ilike(f'%{q}%')) |
            (Document.filename.ilike(f'%{q}%'))
        )
        .limit(search_request.limit)
        .all()
    )

    results = []
    for doc in docs:
        content = doc.content or ''
        plain = clean_snippet(content)  # strip markers for snippet extraction
        idx = plain.lower().find(q.lower())
        snippet = plain[max(0, idx - 80): idx + 220] if idx >= 0 else plain[:220]
        page_num = find_page_for_query(
            doc.file_path or '', q, stored_content=content
        )
        results.append(SearchResult(
            id=str(doc.id),
            score=1.0,
            filename=doc.filename,
            file_path=doc.file_path,
            file_type=doc.file_type or "application/pdf",
            snippet=snippet + "..." if snippet else "",
            author=None,
            creation_date=None,
            page_count=1,
            page_number=page_num,
        ))

    explanation = generate_search_explanation(q, results)
    return SearchResponse(total_results=len(results), results=results, explanation=explanation or None)


# ── Legacy / utility endpoints ────────────────────────────────────────────────

@app.get("/")
async def root():
    return {"message": "Document Manager API v2"}


@app.get("/health")
async def health():
    return {"status": "healthy"}


@app.post("/api/scan")
async def scan(scan_request: ScanRequest, background_tasks: BackgroundTasks,
               current_user: User = Depends(require_admin)):
    background_tasks.add_task(process_scan, scan_request.directory)
    return {"message": "Scan started", "directory": scan_request.directory}


def process_scan(directory: str):
    files = scan_directory(directory)
    processor = DocumentProcessor()
    search_engine = SearchEngine()
    db: Session = SessionLocal()
    try:
        for file_info in files:
            existing = db.query(Document).filter_by(file_hash=file_info.file_hash).first()
            if existing:
                continue

            text = processor.extract_text(file_info.path)
            metadata = processor.extract_metadata(file_info.path)

            doc = Document(
                filename=file_info.filename,
                file_path=file_info.path,
                file_type=file_info.file_type,
                file_size=file_info.file_size,
                file_hash=file_info.file_hash,
                content=text,
                status='indexed',
            )
            db.add(doc)
            db.flush()

            meta = Metadata(
                document_id=doc.id,
                author=metadata.get('author'),
                creation_date=metadata.get('creation_date'),
                language=metadata.get('language'),
                page_count=metadata.get('page_count'),
                custom_tags=metadata.get('custom_tags'),
            )
            db.add(meta)

            search_metadata = {
                'filename': file_info.filename,
                'file_path': file_info.path,
                'file_type': file_info.file_type,
                'author': metadata.get('author'),
                'creation_date': metadata.get('creation_date'),
                'language': metadata.get('language', 'en'),
                'page_count': metadata.get('page_count', 1),
            }
            try:
                search_engine.index_document(str(doc.id), text, search_metadata)
            except Exception:
                pass

        db.commit()
    except Exception as e:
        db.rollback()
        print(f"Scan error: {e}")
    finally:
        db.close()


@app.post("/api/index/init")
async def init_search_index(current_user: User = Depends(require_admin)):
    SearchEngine().create_index()
    return {"message": "Search index initialized"}


@app.post("/api/index/rebuild")
async def rebuild_search_index(
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    search_engine = SearchEngine()
    search_engine.create_index()
    docs = db.query(Document).filter_by(status='indexed').all()
    for doc in docs:
        metadata = db.query(Metadata).filter_by(document_id=doc.id).first()
        search_metadata = {
            'filename': doc.filename,
            'file_path': doc.file_path,
            'file_type': doc.file_type,
            'author': metadata.author if metadata else None,
            'creation_date': metadata.creation_date if metadata else None,
            'language': metadata.language if metadata else 'en',
            'page_count': metadata.page_count if metadata else 1,
        }
        try:
            search_engine.index_document(str(doc.id), doc.content or "", search_metadata)
        except Exception:
            pass
    return {"message": f"Reindexed {len(docs)} documents"}


@app.post("/api/admin/rebuild-vectors")
async def rebuild_vector_index(
    background_tasks: BackgroundTasks,
    current_user: User = Depends(require_admin),
    db: Session = Depends(get_db),
):
    """Re-embed all documents and rebuild the Milvus vector store from scratch."""
    count = db.query(Document).filter(Document.content.isnot(None)).count()
    background_tasks.add_task(_rebuild_vectors_task)
    return {"message": f"Vector rebuild started for {count} documents. "
                       "This runs in the background and may take several minutes."}


def _rebuild_vectors_task():
    db: Session = SessionLocal()
    try:
        # Wipe and recreate the collection
        vs = MilvusVectorStore()
        vs.drop_and_recreate()

        docs = db.query(Document).filter(Document.content.isnot(None)).all()
        total_chunks = 0
        for doc in docs:
            if not doc.content:
                continue
            chunks = chunk_document(doc.content)
            embedded = []
            for chunk in chunks:
                emb = get_embedding(chunk["content"])
                if emb:
                    chunk["embedding"] = emb
                    embedded.append(chunk)
            stored = vs.insert_chunks(str(doc.id), doc.filename, embedded)
            total_chunks += stored
            print(f"[rebuild-vectors] {doc.filename}: {stored}/{len(chunks)} chunks")

        print(f"[rebuild-vectors] Done — {total_chunks} chunks across {len(docs)} documents")
    except Exception as e:
        print(f"[rebuild-vectors] Error: {e}")
    finally:
        db.close()


@app.post("/api/admin/reextract")
async def reextract_all_documents(
    background_tasks: BackgroundTasks,
    current_user: User = Depends(require_admin),
):
    """Re-run text extraction (with OCR fallback) on every document whose file exists."""
    background_tasks.add_task(_reextract_all_task)
    return {"message": "Re-extraction started in background"}


def _reextract_all_task():
    processor = DocumentProcessor()
    search_engine = SearchEngine()
    db: Session = SessionLocal()
    updated = 0
    try:
        docs = db.query(Document).all()
        for doc in docs:
            if not doc.file_path or not os.path.exists(doc.file_path):
                continue
            try:
                new_content = processor.extract_text_with_pages(doc.file_path)
                doc.content = new_content
                db.flush()

                # Re-index in ES
                meta = db.query(Metadata).filter_by(document_id=doc.id).first()
                try:
                    search_engine.index_document(
                        str(doc.id),
                        new_content,
                        {
                            'filename': doc.filename,
                            'file_path': doc.file_path,
                            'file_type': doc.file_type or 'application/pdf',
                            'author': meta.author if meta else None,
                            'creation_date': meta.creation_date if meta else None,
                            'language': meta.language if meta else 'en',
                            'page_count': meta.page_count if meta else 1,
                        },
                    )
                except Exception as es_err:
                    print(f"ES re-index failed for {doc.filename}: {es_err}")

                updated += 1
                print(f"Re-extracted: {doc.filename} ({len(new_content)} chars)")
            except Exception as e:
                print(f"Failed to re-extract {doc.filename}: {e}")

        db.commit()
        print(f"Re-extraction complete: {updated} documents updated")
    except Exception as e:
        db.rollback()
        print(f"Re-extraction task error: {e}")
    finally:
        db.close()


# ── RAG Chatbot endpoint ──────────────────────────────────────────────────────

@app.post("/api/chat/rag", response_model=RagChatResponse)
async def rag_chat(
    chat_request: RagChatRequest,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    query = chat_request.query.strip()
    if not query:
        raise HTTPException(status_code=400, detail="Query cannot be empty")

    try:
        query_lower = query.lower().strip()
        greetings = {"hi", "hello", "hey", "greetings",
                     "good morning", "good afternoon", "good evening"}
        is_greeting = query_lower in greetings or (
            len(query_lower.split()) <= 3 and
            any(query_lower.startswith(g) for g in greetings)
        )

        context_parts: list = []
        sources_info:  list = []

        if not is_greeting:
            token_budget = chat_request.max_context_tokens

            # ── Primary: Milvus semantic search ──────────────────────────────
            semantic_hits: list = []
            query_emb = get_embedding(query)
            if query_emb:
                vs = MilvusVectorStore()
                semantic_hits = vs.search(query_emb, limit=12, min_score=0.35)

                # Expand context: fetch adjacent chunks (±1) for top 4 hits
                seen_pairs: set = {(h["doc_id"], h["chunk_index"]) for h in semantic_hits}
                extra: list = []
                for hit in semantic_hits[:4]:
                    for adj in vs.get_adjacent_chunks(hit["doc_id"], hit["chunk_index"]):
                        key = (adj["doc_id"], adj["chunk_index"])
                        if key not in seen_pairs:
                            seen_pairs.add(key)
                            extra.append(adj)
                all_chunks = semantic_hits + extra
            else:
                all_chunks = []

            # ── Supplementary: ES keyword search (always runs) ────────────────
            # Catches exact-match terms that semantic search may miss
            es_doc_ids: set = {h["doc_id"] for h in all_chunks}
            try:
                se = SearchEngine()
                raw_es = se.search(query=query, limit=5)
                for r in raw_es.get("results", []):
                    if r["id"] in es_doc_ids:
                        continue   # already covered by semantic results
                    doc = db.query(Document).filter(Document.id == r["id"]).first()
                    if not doc:
                        continue
                    plain = clean_snippet(doc.content or "")
                    first_word = query.lower().split()[0] if query.split() else ""
                    idx = plain.lower().find(first_word) if first_word else -1
                    snippet = plain[max(0, idx - 100): idx + 600] if idx >= 0 else plain[:600]
                    pg = find_page_for_query(doc.file_path or "", query,
                                             stored_content=doc.content or "")
                    context_parts.append(
                        f"[Source: {doc.filename} — Page {pg}]\n{snippet}\n"
                    )
                    sources_info.append({
                        "filename":    doc.filename,
                        "id":          str(doc.id),
                        "score":       round(r.get("score", 1.0), 2),
                        "page_number": pg,
                        "excerpt":     snippet[:300].strip(),
                    })
            except Exception:
                pass

            # ── Assemble context from semantic chunks ─────────────────────────
            # Group by document, sort each doc's chunks by chunk_index
            doc_chunk_map: dict = defaultdict(list)
            for c in all_chunks:
                doc_chunk_map[c["doc_id"]].append(c)
            for did in doc_chunk_map:
                doc_chunk_map[did].sort(key=lambda x: x["chunk_index"])

            # Sort documents by their best semantic score (highest first)
            doc_best_score: dict = {}
            for h in semantic_hits:
                did = h["doc_id"]
                if did not in doc_best_score or h["score"] > doc_best_score[did]:
                    doc_best_score[did] = h["score"]
            ordered_docs = sorted(doc_chunk_map.keys(),
                                  key=lambda d: doc_best_score.get(d, 0), reverse=True)

            tokens_used = sum(len(p) // 4 for p in context_parts)
            for doc_id in ordered_docs:
                chunks = doc_chunk_map[doc_id]
                best = max(chunks, key=lambda x: x.get("score", 0))

                # Join adjacent chunks; insert "…" where there is a gap
                merged_parts: list = []
                prev_idx = -2
                for c in chunks:
                    if prev_idx >= 0 and c["chunk_index"] > prev_idx + 1:
                        merged_parts.append("…")
                    merged_parts.append(c["content"])
                    prev_idx = c["chunk_index"]
                merged_text = " ".join(merged_parts)

                chunk_tokens = len(merged_text) // 4
                if tokens_used + chunk_tokens > token_budget:
                    break
                tokens_used += chunk_tokens

                context_parts.insert(
                    len([p for p in context_parts if "[Source:" in p]),
                    f"[Source: {best['filename']} — Page {best['page_number']}]\n"
                    f"{merged_text}\n",
                )
                sources_info.insert(0, {
                    "filename":    best["filename"],
                    "id":          doc_id,
                    "score":       doc_best_score.get(doc_id, 0),
                    "page_number": best["page_number"],
                    "excerpt":     merged_text[:300].strip(),
                })

            # Deduplicate sources_info by doc id (semantic entries come first)
            seen_src: set = set()
            deduped_sources: list = []
            for s in sources_info:
                key = s["id"]
                if key not in seen_src:
                    seen_src.add(key)
                    deduped_sources.append(s)
            sources_info = deduped_sources

        # ── Build prompt and call LLM ─────────────────────────────────────────
        SYSTEM = (
            "You are Docunova, a precise document assistant.\n"
            "Rules (follow strictly):\n"
            "1. Base your answer SOLELY on the document excerpts provided — "
            "never use external knowledge.\n"
            "2. Always cite sources using the format: "
            "(Document: <filename>, Page <N>).\n"
            "3. When accuracy matters (definitions, numbers, dates, names), "
            "quote the relevant passage verbatim before paraphrasing.\n"
            "4. If the answer spans multiple documents, synthesize and cite each one.\n"
            "5. If the excerpts do not contain sufficient information, respond exactly: "
            "'I could not find this in the uploaded documents.' — do not speculate.\n"
            "6. Answer the question directly and concisely, then provide citations."
        )

        if is_greeting:
            ai_response = _call_ollama(
                "You are Docunova, a friendly document assistant. "
                "Respond warmly to the greeting but do not answer any knowledge questions.",
                f"User said: {query}",
                max_tokens=80,
            ) or "Hello! I'm Docunova. Ask me anything about your uploaded documents."
        elif not context_parts:
            ai_response = (
                "I could not find any uploaded documents matching your query. "
                "Please try different keywords, or ask the administrator to upload relevant files."
            )
        else:
            context_text = "\n---\n".join(context_parts)
            user_msg = (
                f"Document excerpts:\n\n{context_text}\n\n"
                f"---\nQuestion: {query}\n\n"
                "Answer using only the excerpts above. "
                "Quote key passages and cite each source (Document: <filename>, Page <N>)."
            )
            ai_response = _call_ollama(SYSTEM, user_msg, max_tokens=800)
            if not ai_response:
                # Ollama unavailable — show raw excerpt
                src = sources_info[0] if sources_info else {}
                ai_response = (
                    f"Relevant passage from {src.get('filename', 'the document')} "
                    f"(Page {src.get('page_number', 1)}):\n\n"
                    + context_parts[0].strip()
                )

        return RagChatResponse(
            response=ai_response,
            sources=sources_info,
            total_sources=len(sources_info),
        )

    except HTTPException:
        raise
    except Exception as e:
        print(f"RAG chat error: {e}")
        raise HTTPException(status_code=500, detail="Failed to generate response")
