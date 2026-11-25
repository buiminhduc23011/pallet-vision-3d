"""Enforce byte limits before multipart parsing/spooling, including chunked bodies."""

from fastapi.responses import JSONResponse


class BodyTooLarge(Exception):
    pass


class BodyLimitMiddleware:
    def __init__(self, app):
        self.app = app

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["method"] in ("GET", "HEAD", "OPTIONS"):
            await self.app(scope, receive, send)
            return
        engine = getattr(scope["app"].state, "engine", None)
        limit = (engine.config.get().runtime.max_upload_mb if engine else 512) * 1024 * 1024 + 65536
        if scope["path"] != "/api/v1/assets":
            limit = min(limit, 1024 * 1024)
        total, exceeded, response_started = 0, False, False

        async def bounded_receive():
            nonlocal total, exceeded
            message = await receive()
            if message["type"] == "http.request":
                total += len(message.get("body", b""))
                if total > limit:
                    exceeded = True
                    raise BodyTooLarge()
            return message

        async def bounded_send(message):
            nonlocal response_started
            if exceeded:
                return
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        try:
            await self.app(scope, bounded_receive, bounded_send)
        except BodyTooLarge:
            exceeded = True
        if exceeded and not response_started:
            response = JSONResponse(
                {"error": {"code": "UPLOAD_TOO_LARGE", "message": "Request exceeds configured byte limit"}},
                status_code=413,
            )
            await response(scope, receive, send)
