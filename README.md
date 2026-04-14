# Jarvis AI Adaptive Learning Assistant

AI-powered study companion that ingests notes or documents, asks adaptive questions, and adjusts difficulty based on learner performance.

## Architecture

- Frontend: React + Tailwind (Vite)
- Backend: FastAPI
- Database: PostgreSQL
- Vector Store: pgvector extension in PostgreSQL
- LLM features: optional OpenAI API for embeddings, question generation, and answer evaluation

## Features

- Upload `.txt`, `.pdf`, `.docx` study material
- Parse and chunk text for retrieval
- Store documents persistently in PostgreSQL with hash-based de-duplication
- Store embeddings in PostgreSQL `pgvector` and retrieve context using vector similarity search
- Generate practice questions from document content
- Adaptive difficulty controller:
  - Correct answer => increase difficulty (`easy -> medium -> hard`)
  - Incorrect answer => decrease difficulty (`hard -> medium -> easy`)
- Reuse previously uploaded documents for future practice
- JWT authentication with per-user document/session isolation

## Folder Structure

```text
jarvis-ai-assistant/
  backend/
    app/
      routers/
      services/
      main.py
      models.py
  frontend/
    src/
  docker-compose.yml
```

## 1) Start PostgreSQL + pgvector

```bash
docker compose up -d
```

## 2) Run Backend (FastAPI)

```bash
cd backend
python -m venv .venv
# Windows PowerShell:
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
copy .env.example .env
uvicorn app.main:app --reload --port 8000
```

Backend runs at `http://localhost:8000`.

## 3) Run Frontend (React)

Open a second terminal:

```bash
cd frontend
npm install
npm run dev
```

Frontend runs at `http://localhost:5173`.

## API Overview

- `POST /api/auth/register` create account
- `POST /api/auth/login` get bearer token
- `POST /api/documents/upload` upload study document
- `GET /api/documents` list uploaded documents
- `POST /api/practice/start` create practice session
- `GET /api/practice/{session_id}/question` fetch next adaptive question
- `POST /api/practice/answer` evaluate answer and update difficulty

All `/api/documents/*` and `/api/practice/*` endpoints require `Authorization: Bearer <token>`.

## OpenAI Integration (Optional)

Set these in `backend/.env`:

```env
OPENAI_API_KEY=your_key
OPENAI_MODEL=gpt-4o-mini
EMBEDDING_MODEL=text-embedding-3-small
JWT_SECRET_KEY=replace_with_a_long_secret
JWT_ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=1440
```

If `OPENAI_API_KEY` is missing, the app uses deterministic fallback logic so local testing still works.

## Run Tests

```bash
cd backend
pytest -q
```

## Next Improvements

- Add spaced-repetition scheduling
- Add session analytics dashboard
- Add integration tests for auth + upload + adaptive-practice end-to-end
