from fastapi import Request

from app.core.security import decode_access_token


class AuthContextMiddleware:
    def __init__(self, app) -> None:
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        request = Request(scope, receive=receive)
        auth_header = request.headers.get("authorization", "")
        user_id = None
        auth_error = None

        if auth_header.lower().startswith("bearer "):
            token = auth_header.split(" ", 1)[1].strip()
            if token:
                user_id = await decode_access_token(token)
                if not user_id:
                    auth_error = "Invalid token"
            else:
                auth_error = "Invalid token"

        scope.setdefault("state", {})
        scope["state"]["user_id"] = user_id
        scope["state"]["auth_error"] = auth_error

        await self.app(scope, receive, send)

