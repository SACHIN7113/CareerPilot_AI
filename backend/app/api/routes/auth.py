import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from motor.motor_asyncio import AsyncIOMotorDatabase

from app.config.db import COLLECTIONS, get_db
from app.core.dependencies import get_current_user
from app.models.api_schemas import ChangePasswordRequest, LoginRequest, MessageOut, TokenOut, UserCreateRequest, UserOut
from app.core.security import create_access_token, hash_password, verify_password

router = APIRouter()


@router.post("/register", response_model=UserOut)
async def register(payload: UserCreateRequest, db: AsyncIOMotorDatabase = Depends(get_db)) -> UserOut:
    users = db[COLLECTIONS["users"]]
    existing = await users.find_one({"email": payload.email.lower()})
    if existing:
        raise HTTPException(status_code=409, detail="Email already registered")

    user_id = str(uuid.uuid4())
    created_at = datetime.now(timezone.utc)
    user = {
        "_id": user_id,
        "name": payload.name.strip() or "Learner",
        "email": payload.email.lower(),
        "password_hash": await hash_password(payload.password),
        "created_at": created_at,
    }
    await users.insert_one(user)
    return UserOut(id=user_id, name=user["name"], email=user["email"], created_at=created_at)


@router.post("/login", response_model=TokenOut)
async def login(payload: LoginRequest, db: AsyncIOMotorDatabase = Depends(get_db)) -> TokenOut:
    users = db[COLLECTIONS["users"]]
    user = await users.find_one({"email": payload.email.lower()})
    if not user or not await verify_password(payload.password, user["password_hash"]):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid credentials")

    token = await create_access_token(str(user["_id"]))
    return TokenOut(access_token=token, name=user["name"], email=user["email"])


@router.post("/change-password", response_model=MessageOut)
async def change_password(
    payload: ChangePasswordRequest,
    current_user: dict = Depends(get_current_user),
    db: AsyncIOMotorDatabase = Depends(get_db),
) -> MessageOut:
    if payload.current_password == payload.new_password:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="New password must be different")

    current_hash = str(current_user.get("password_hash") or "")
    if not current_hash or not await verify_password(payload.current_password, current_hash):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Current password is incorrect")

    users = db[COLLECTIONS["users"]]
    await users.update_one(
        {"_id": str(current_user["_id"])},
        {"$set": {"password_hash": await hash_password(payload.new_password)}},
    )
    return MessageOut(message="Password updated successfully")


