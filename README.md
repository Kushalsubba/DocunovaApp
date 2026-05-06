# DocunovaApp — Document Management & RAG Chatbot

## Project Structure

```
DocunovaApp/
├── backend/          Python FastAPI backend (port 8001)
│   ├── main.py       API routes (documents, auth, RAG chat, search)
│   ├── models.py     SQLAlchemy DB models
│   ├── auth.py       JWT authentication
│   ├── config.py     App configuration
│   ├── database.py   SQLite/PostgreSQL setup
│   ├── document_processor.py   PDF/image/office text extraction
│   ├── vector_store.py         Milvus vector embeddings (RAG)
│   ├── search.py     Elasticsearch keyword search
│   ├── file_scanner.py
│   ├── run.py        Entry point
│   └── requirements.txt
└── frontend/         React + Vite frontend (port 8002)
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

## Prerequisites (one-time — must be running)

| Service        | Port  | Start command                          |
|----------------|-------|----------------------------------------|
| PostgreSQL      | 5433  | `docker compose up -d` (project root) |
| Elasticsearch   | 9200  | same docker compose                    |
| Ollama (LLM)    | 11434 | already running as Docker container    |

## How to Run

### 1 — Start the Backend

```bash
cd /home/ashok/Desktop/DocunovaApp/backend

# Install dependencies (first time only)
pip install -r requirements.txt

# Start the server
python run.py
# → runs on http://localhost:8001
```

### 2 — Start the Frontend

```bash
cd /home/ashok/Desktop/DocunovaApp/frontend

# Install dependencies (first time only)
npm install

# Start the dev server
npm run dev
# → runs on http://localhost:8002
```

### 3 — Open in Browser

- **App:** http://localhost:8002
- **API docs:** http://localhost:8001/docs

## Default Accounts

| Role  | Username | Password |
|-------|----------|----------|
| Admin | admin    | admin    |
| User  | user     | password |

## Notes

- `uploads/` and database files (`*.db`) are **runtime data** — not in this source folder. They live alongside the running backend.
- `node_modules/` is excluded — run `npm install` to regenerate.
- Use **Anaconda Python** (`/home/ashok/anaconda3/bin/python3`) for the backend.
