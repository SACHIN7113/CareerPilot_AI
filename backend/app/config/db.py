import logging
from motor.motor_asyncio import AsyncIOMotorClient, AsyncIOMotorDatabase
from pymongo import ASCENDING, DESCENDING
from pymongo.errors import PyMongoError

from app.config.settings import settings

logger = logging.getLogger(__name__)


def _build_mongo_client(url: str) -> AsyncIOMotorClient:
    kwargs: dict[str, int | str] = {
        "serverSelectionTimeoutMS": settings.mongodb_server_selection_timeout_ms,
        "connectTimeoutMS": settings.mongodb_connect_timeout_ms,
        "socketTimeoutMS": settings.mongodb_socket_timeout_ms,
    }

    # Atlas SRV connections are TLS by default. Providing a CA bundle is often
    # required on some Windows/Python environments to avoid handshake failures.
    if url.startswith("mongodb+srv://"):
        try:
            import certifi  # type: ignore

            kwargs["tlsCAFile"] = certifi.where()
        except Exception:
            logger.debug("certifi not available; continuing without explicit tlsCAFile")

    return AsyncIOMotorClient(url, **kwargs)


def _set_mongo_target(url: str) -> None:
    global mongo_client, mongo_db
    mongo_client = _build_mongo_client(url)
    mongo_db = mongo_client[settings.mongodb_database_name]


mongo_client: AsyncIOMotorClient
mongo_db: AsyncIOMotorDatabase
_set_mongo_target(settings.mongodb_url)

# Legacy compatibility for modules that may still import Base.
Base = object

COLLECTIONS = {
    "users": "users",
    "documents": "documents",
    "document_chunks": "document_chunks",
    "practice_sessions": "practice_sessions",
    "question_attempts": "question_attempts",
    "analysis_records": "analysis_records",
}


async def get_db() -> AsyncIOMotorDatabase:
    return mongo_db


async def init_mongo_collections() -> None:
    try:
        await _init_collections_and_indexes()
        return
    except PyMongoError as exc:
        logger.error("MongoDB connection failed during startup: %s", exc)

        should_try_fallback = (
            settings.mongodb_fallback_to_local
            and settings.mongodb_url.strip() != settings.mongodb_fallback_url.strip()
        )

        if should_try_fallback:
            logger.warning("Trying fallback MongoDB URL: %s", settings.mongodb_fallback_url)
            _set_mongo_target(settings.mongodb_fallback_url)
            try:
                await _init_collections_and_indexes()
                logger.warning("Connected to fallback MongoDB successfully.")
                return
            except PyMongoError as fallback_exc:
                logger.error("Fallback MongoDB connection also failed: %s", fallback_exc)

        if settings.mongodb_allow_start_without_connection:
            logger.warning(
                "Starting app without active MongoDB connection. DB-backed endpoints may fail until the database is reachable."
            )
            return

        raise


async def _init_collections_and_indexes() -> None:
    existing = set(await mongo_db.list_collection_names())
    for name in COLLECTIONS.values():
        if name not in existing:
            await mongo_db.create_collection(name)

    await mongo_db[COLLECTIONS["users"]].create_index([("email", ASCENDING)], unique=True)
    await mongo_db[COLLECTIONS["documents"]].create_index(
        [("owner_id", ASCENDING), ("content_hash", ASCENDING)], unique=True
    )
    await mongo_db[COLLECTIONS["documents"]].create_index([("owner_id", ASCENDING), ("created_at", DESCENDING)])
    await mongo_db[COLLECTIONS["document_chunks"]].create_index(
        [("document_id", ASCENDING), ("chunk_index", ASCENDING)], unique=True
    )
    await mongo_db[COLLECTIONS["document_chunks"]].create_index([("owner_id", ASCENDING), ("document_id", ASCENDING)])
    await mongo_db[COLLECTIONS["practice_sessions"]].create_index([("document_id", ASCENDING), ("created_at", DESCENDING)])
    await mongo_db[COLLECTIONS["practice_sessions"]].create_index([("owner_id", ASCENDING), ("created_at", DESCENDING)])
    await mongo_db[COLLECTIONS["question_attempts"]].create_index([("session_id", ASCENDING), ("created_at", ASCENDING)])
    await mongo_db[COLLECTIONS["question_attempts"]].create_index([("owner_id", ASCENDING), ("created_at", DESCENDING)])
    await mongo_db[COLLECTIONS["analysis_records"]].create_index([("owner_id", ASCENDING), ("created_at", DESCENDING)])
    await mongo_db[COLLECTIONS["analysis_records"]].create_index(
        [("owner_id", ASCENDING), ("jd_content_hash", ASCENDING), ("resume_content_hash", ASCENDING)]
    )

