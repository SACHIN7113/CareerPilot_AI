import asyncio

from app.core.security import create_access_token, decode_access_token, hash_password, verify_password


def _run(coro):
    return asyncio.run(coro)


def test_password_hashing_roundtrip() -> None:
    plain = "secret123"
    hashed = _run(hash_password(plain))
    assert plain != hashed
    assert _run(verify_password(plain, hashed))


def test_access_token_encode_decode() -> None:
    subject = "demo-user-id"
    token = _run(create_access_token(subject))
    assert _run(decode_access_token(token)) == subject
