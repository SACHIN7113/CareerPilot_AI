# CareerPilot AI

CareerPilot AI is an adaptive interview preparation platform. It helps users analyze resume-to-JD fit, identify missing skills, generate focused roadmaps, run HR and MCQ assessments, and practice adaptive interview questions.

## Current Tech Stack

- Frontend: React + Vite + Tailwind CSS
- Backend: FastAPI
- Database: MongoDB (Motor + PyMongo)
- AI services: Google Gemini (with fallback behavior in multiple flows)
- Auth: JWT bearer tokens

## Current Product Functionality

### 1. Authentication and Account
- Register and login with JWT session handling
- Change password from settings
- Per-user data isolation for documents, sessions, and analysis records

### 2. Resume vs JD Analysis Flow
- Upload both JD and resume (PDF, DOCX, TXT)
- Generate role-fit insights and match output
- Extract key matched skills, missing skills, and summary guidance
- Save each analysis as an `analysis_record` for later steps

### 3. Skill Gap to Learning Plan
- Start skill update from an analysis record
- Build roadmap for a selected target skill/role
- Generate step-based learning assessments
- Evaluate step assessments with score, pass threshold, and feedback

### 4. Assessment Modules
- HR practice question generation + answer evaluation
- JD-based MCQ assessment (start + evaluate)
- Resume-based assessment (start + evaluate)

### 5. AI Prepare (Adaptive Practice)
- Start a practice session from uploaded documents
- Retrieve contextual chunks and generate adaptive questions
- Difficulty adjustment based on correctness (`easy -> medium -> hard` and reverse)
- Answer evaluation with feedback + reference answer

### 6. Document Intelligence
- Upload and parse documents (`.txt`, `.pdf`, `.docx`)
- SHA-256 hash based dedup per user
- Chunking + embeddings for retrieval
- Auto-generated JD overview data (role, skills, requirements, prep hints)

### 7. History and Settings
- Upload history and activity view
- Basic learning momentum stats
- Profile preferences and local session visibility controls

## Project Structure

```text
jarvis-ai-assistant/
  backend/
    app/
      main.py
      config/
      routes/
      services/
      models/
    tests/
  frontend/
    src/
      pages/
      routes/
      components/
      api/
```

## Local Setup

## 1) Start MongoDB

Use local MongoDB (default expected at `mongodb://localhost:27017`).

Or run MongoDB directly with Docker:

```bash
docker run -d --name careerpilot-mongo -p 27017:27017 mongo:7
```

## 2) Configure Backend Environment

Create `backend/.env` with values like:

```env
MONGODB_URL=mongodb://localhost:27017
MONGODB_DATABASE_NAME=jarvis_db
MONGODB_FALLBACK_URL=mongodb://localhost:27017

JWT_SECRET_KEY=replace_with_a_long_secret
JWT_ALGORITHM=HS256
ACCESS_TOKEN_EXPIRE_MINUTES=1440

GEMINI_API_KEY=
GEMINI_MODEL=gemini-2.0-flash
GEMINI_MODEL_FALLBACKS=models/gemini-2.5-flash,models/gemini-2.0-flash,models/gemini-2.5-flash-lite,models/gemini-flash-lite-latest
GEMINI_EMBEDDING_MODEL=models/embedding-001
EMBEDDING_DIMENSIONS=1536

CORS_ORIGINS=http://localhost:5173
ANALYSIS_FAST_MODE=true
ANALYSIS_LLM_REFINEMENT=true
```

`GEMINI_API_KEY` is optional for basic local runs, but recommended for best quality in analysis and roadmap features.

## 3) Run Backend

```bash
cd backend
python -m venv .venv
# Windows PowerShell
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
uvicorn app.main:app --reload --port 8000
```

Backend URL: `http://localhost:8000`

## 4) Run Frontend

Make sure frontend env file exists:

```env
VITE_API_URL=http://localhost:8000
```

Then run frontend:

```bash
cd frontend
npm install
npm run dev
```

Frontend URL: `http://localhost:5173`

## API Surface (Current)

### Health
- `GET /health`

### Auth
- `POST /api/auth/register`
- `POST /api/auth/login`
- `POST /api/auth/change-password`

### Documents
- `GET /api/documents`
- `GET /api/documents/count`
- `POST /api/documents/upload`

### Adaptive Practice
- `POST /api/practice/start`
- `GET /api/practice/{session_id}/question`
- `POST /api/practice/answer`

### Analysis and Assessments
- `POST /api/analysis/match`
- `POST /api/analysis/hr-practice/start`
- `POST /api/analysis/hr-practice/evaluate`
- `POST /api/analysis/skill-update/start`
- `POST /api/analysis/skill-update/roadmap`
- `POST /api/analysis/skill-update/step-assessment/start`
- `POST /api/analysis/skill-update/step-assessment/evaluate`
- `POST /api/analysis/mcq-assessment/start`
- `POST /api/analysis/mcq-assessment/evaluate`
- `POST /api/analysis/resume-assessment/start`
- `POST /api/analysis/resume-assessment/evaluate`

Most endpoints (except health and auth login/register) require:

```http
Authorization: Bearer <token>
```

## Frontend Routes (Current)

- `/` onboarding
- `/login` login/register
- `/analysis` analysis landing
- `/analysis/process` analysis processing screen
- `/analysis/skill-update` missing-skill and roadmap flow
- `/analysis/skill-quiz` step-based learning quiz
- `/analysis/assessment` assessment view
- `/aiPrepare` adaptive interview chat practice
- `/documents` JD/document intelligence and history
- `/history` activity and upload history
- `/settings` account and preferences
- `/settings/password` change password

## Testing

Run backend tests:

```bash
cd backend
pytest -q
```

## Notes

- Backend runtime is MongoDB-based.
- Frontend API base URL is configured through `VITE_API_URL`.
