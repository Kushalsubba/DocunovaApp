# DocunovaApp — Document Management & RAG Chatbot

## Project Structure

```
DocunovaApp/
├── docker-compose.yml    All services (recommended)
├── .env.example          Environment variable template
├── backend/              Python FastAPI backend (port 8001)
│   ├── Dockerfile
│   ├── main.py           API routes (documents, auth, RAG chat, search)
│   ├── models.py         SQLAlchemy DB models
│   ├── auth.py           JWT authentication
│   ├── config.py         App configuration
│   ├── database.py       PostgreSQL setup
│   ├── document_processor.py   PDF/image/office text extraction
│   ├── vector_store.py         Milvus vector embeddings (RAG)
│   ├── search.py         Elasticsearch keyword search
│   ├── file_scanner.py
│   ├── run.py            Entry point
│   └── requirements.txt
└── frontend/             React + Vite frontend (port 8002)
    ├── Dockerfile
    ├── nginx.conf
    ├── src/
    │   ├── App.tsx
    │   ├── DashboardPage.tsx
    │   ├── AdminDocumentsPanel.tsx   Document library + category filter
    │   ├── UserChatBot.tsx           Docunova RAG chatbot
    │   ├── LoginPage.tsx
    │   ├── RegisterPage.tsx
    │   └── index.css
    ├── package.json
    └── vite.config.ts
```

---

## Option A — Run with Docker (Recommended)

Runs the full stack (PostgreSQL, Elasticsearch, Ollama, backend, frontend) in containers.

### Prerequisites

- [Docker](https://docs.docker.com/get-docker/) with Compose plugin

### Steps

**1. Copy and configure environment variables**

```bash
cp .env.example .env
# Edit .env and set a strong JWT_SECRET before going to production
```

**2. Build and start all services**

```bash
docker compose up --build
```

First build takes a few minutes (installing Python/Node deps, pulling images).

**3. Pull Ollama models (first time only)**

Open a new terminal while the containers are running:

```bash
docker compose exec ollama ollama pull llama3.2
docker compose exec ollama ollama pull nomic-embed-text
```

**4. Open in browser**

| URL | Description |
|-----|-------------|
| http://localhost:8002 | Main application (UI) |
| http://localhost:8001/docs | FastAPI Swagger API docs |

**Useful Docker commands**

```bash
# Run in background
docker compose up --build -d

# View logs
docker compose logs -f backend
docker compose logs -f frontend

# Stop everything
docker compose down

# Stop and wipe all data volumes
docker compose down -v
```

---

## Option B — Run Locally (Development)

### Prerequisites

- Anaconda Python (for the backend)
- Node.js 18+ (for the frontend)
- The following services running:

| Service | Port | Start command |
|---------|------|---------------|
| PostgreSQL | 5433 | `docker run -e POSTGRES_USER=user -e POSTGRES_PASSWORD=password -e POSTGRES_DB=doc_scanner -p 5433:5432 postgres:16-alpine` |
| Elasticsearch | 9200 | `docker run -e discovery.type=single-node -e xpack.security.enabled=false -p 9200:9200 docker.elastic.co/elasticsearch/elasticsearch:8.12.0` |
| Ollama | 11434 | `docker run -p 11434:11434 ollama/ollama` |

### 1 — Start the Backend

```bash
cd /home/ashok/Desktop/DocunovaApp/backend

# Install dependencies (first time only)
/home/ashok/anaconda3/bin/pip install -r requirements.txt

# Start the server
/home/ashok/anaconda3/bin/python3 run.py
# → API running at http://localhost:8001
# → Swagger docs at http://localhost:8001/docs
```

Run in the background:

```bash
/home/ashok/anaconda3/bin/python3 run.py > backend.log 2>&1 &
```

### 2 — Start the Frontend

```bash
cd /home/ashok/Desktop/DocunovaApp/frontend

# Install dependencies (first time only)
npm install

# Start the dev server
npm run dev
# → App running at http://localhost:8002
```

Run in the background:

```bash
npm run dev > /tmp/frontend.log 2>&1 &
```

### 3 — Pull Ollama Models (first time only)

```bash
ollama pull llama3.2
ollama pull nomic-embed-text
```

---

## Default Accounts

| Role  | Username | Password |
|-------|----------|----------|
| Admin | admin    | admin    |
| User  | user     | password |

---

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `JWT_SECRET` | `change-this-secret-in-production` | JWT signing secret — **change this** |
| `DATABASE_URL` | `postgresql://user:password@localhost:5433/doc_scanner` | PostgreSQL connection string |
| `ELASTICSEARCH_URL` | `http://localhost:9200` | Elasticsearch URL |
| `OLLAMA_URL` | `http://localhost:11434` | Ollama LLM server URL |
| `OLLAMA_MODEL` | `llama3.2:latest` | LLM model used for RAG chat |
| `EMBEDDING_MODEL` | `nomic-embed-text:latest` | Ollama embedding model |
| `MILVUS_DB_PATH` | `backend/milvus_kush.db` | Milvus Lite vector DB file path |
| `UPLOAD_DIR` | `backend/uploads/` | Directory for uploaded files |
| `SCAN_DIRECTORY` | `/mnt/data/documents` | Directory auto-scanned for documents |

---

## Notes

- In Docker, nginx on port 8002 proxies all `/api/` requests to the backend — no CORS issues.
- `uploads/`, `*.db`, and `backend.log` are runtime data — not committed to version control.
- Use **Anaconda Python** for local backend — system Python may lack required packages.
- `node_modules/` is excluded from version control — run `npm install` to regenerate.
