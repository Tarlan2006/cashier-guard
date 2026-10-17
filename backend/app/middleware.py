"""Bound upload body reception before FastAPI's multipart parser runs."""
import asyncio
import hmac
import time

from starlette.formparsers import MultiPartException
from starlette.responses import JSONResponse


class UploadBudgetMiddleware:
    def __init__(self, app, settings, reserve_upload=None, release_upload=None):
        self.app = app
        self.settings = settings
        self.inflight = 0
        self.reserve_upload = reserve_upload
        self.release_upload = release_upload

    async def __call__(self, scope, receive, send):
        if scope["type"] != "http" or scope["path"] != "/api/v1/analyze" or scope["method"] != "POST":
            return await self.app(scope, receive, send)
        config = self.settings
        started_mono, started_at = time.monotonic(), time.time()
        scope.setdefault("state", {}).update(upload_started_mono=started_mono, upload_started_at=started_at)
        headers = dict(scope.get("headers", []))
        key = headers.get(b"x-api-key", b"")
        if not key or not hmac.compare_digest(key, config.api_key.encode()):
            response = JSONResponse({"detail": "Неверный ключ API. Проверьте ключ доступа.", "error_code": "UNAUTHORIZED"}, 401)
            # Commit the authentication status before discarding bytes. Otherwise
            # an upstream proxy can race a closed upload socket and emit 500/EPIPE.
            await send({"type": "http.response.start", "status": 401, "headers": response.raw_headers})
            remaining_bytes = config.max_upload_mb * 1024 * 1024 + 64 * 1024
            deadline = started_mono + min(2.0, config.upload_timeout, config.timeout)
            try:
                # No multipart parsing, temporary file or pipeline is involved.
                while remaining_bytes > 0:
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        break
                    message = await asyncio.wait_for(receive(), remaining)
                    if message["type"] == "http.disconnect":
                        break
                    if message["type"] == "http.request":
                        remaining_bytes -= len(message.get("body", b""))
                        if not message.get("more_body", False):
                            break
            except (TimeoutError, OSError):
                pass
            await send({"type": "http.response.body", "body": response.body})
            return
        if self.inflight >= config.max_concurrent_uploads:
            return await JSONResponse({"detail": "Сервер принимает другие загрузки. Повторите позже.", "error_code": "UPLOAD_BUSY"}, 503)(scope, receive, send)
        # Permit a bounded multipart envelope; the file has its own exact limit.
        limit = config.max_upload_mb * 1024 * 1024 + 64 * 1024
        try:
            declared = int(headers.get(b"content-length", b"0"))
        except ValueError:
            declared = 0
        if declared > limit:
            return await JSONResponse({"detail": "Превышен допустимый размер загрузки.", "error_code": "UPLOAD_TOO_LARGE"}, 413)(scope, receive, send)
        received = 0
        reservation_token = object()
        failure = None
        response_started = False
        upload_budget = min(config.upload_timeout, config.timeout)

        async def limited_receive():
            nonlocal received, failure
            remaining = upload_budget - (time.monotonic() - started_mono)
            try:
                if remaining <= 0:
                    raise TimeoutError
                message = await asyncio.wait_for(receive(), remaining)
            except TimeoutError:
                failure = (408, "TIMEOUT", "Истекло время загрузки. Выберите меньший файл или повторите попытку.")
                # The parser catches this type and closes any spooled temporary files.
                raise MultiPartException(failure[2])
            if message["type"] == "http.disconnect":
                failure = (400, "UPLOAD_INTERRUPTED", "Загрузка прервана. Выберите файл и повторите попытку.")
                raise MultiPartException(failure[2])
            if message["type"] == "http.request":
                chunk_size = len(message.get("body", b""))
                received += chunk_size
                if received > limit:
                    failure = (413, "UPLOAD_TOO_LARGE", "Превышен допустимый размер загрузки.")
                    raise MultiPartException(failure[2])
                if self.reserve_upload is not None and not self.reserve_upload(reservation_token, chunk_size):
                    failure = (503, "STORAGE_FULL", "На сервере недостаточно места для загрузки. Повторите позже.")
                    raise MultiPartException(failure[2])
            return message

        async def guarded_send(message):
            nonlocal response_started
            if failure:
                # Replace the multipart parser's generic 400 with the actual cause.
                if not response_started:
                    response_started = True
                    status, code, detail = failure
                    await JSONResponse({"detail": detail, "error_code": code}, status)(scope, receive, send)
                return
            if message["type"] == "http.response.start":
                response_started = True
            await send(message)

        self.inflight += 1
        try:
            await self.app(scope, limited_receive, guarded_send)
        finally:
            self.inflight -= 1
            if self.release_upload is not None:
                self.release_upload(reservation_token)
