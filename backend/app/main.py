from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.config import init_mongo_collections, settings
from app.middlewares.auth_middleware import AuthContextMiddleware
from app.routes import analysis, auth, documents, practice
from app.models.api_schemas import HealthOut

app = FastAPI(title="CareerPilot AI Adaptive Learning Assistant", version="0.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=[origin.strip() for origin in settings.cors_origins.split(",") if origin.strip()],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(AuthContextMiddleware)


@app.on_event("startup")
async def startup() -> None:
    await init_mongo_collections()


@app.get("/health", response_model=HealthOut)
async def health() -> HealthOut:
    return HealthOut(status="ok")

# this is the start of the file
@app.get("/")
def root():
    return {"message": "CareerPilot AI Backend Running "}

app.include_router(documents.router, prefix="/api/documents", tags=["documents"])
app.include_router(practice.router, prefix="/api/practice", tags=["practice"])
app.include_router(auth.router, prefix="/api/auth", tags=["auth"])
app.include_router(analysis.router, prefix="/api/analysis", tags=["analysis"])

