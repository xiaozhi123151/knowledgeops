from starlette.responses import JSONResponse


class BodyLimitExceeded(Exception):
    pass


class RequestBodyLimit:
    """Cap received bytes before the multipart parser can spool an unbounded upload."""
    def __init__(self, app, max_bytes):
        self.app, self.max_bytes = app, max_bytes

    async def __call__(self, scope, receive, send):
        if scope['type'] != 'http':
            return await self.app(scope, receive, send)
        content_length = dict(scope.get('headers', [])).get(b'content-length')
        if content_length:
            try:
                if int(content_length) > self.max_bytes:
                    return await JSONResponse({'detail': 'REQUEST_TOO_LARGE'}, status_code=413)(scope, receive, send)
            except ValueError:
                return await JSONResponse({'detail': 'INVALID_CONTENT_LENGTH'}, status_code=400)(scope, receive, send)
        total = 0
        started = False
        async def limited_receive():
            nonlocal total
            message = await receive()
            total += len(message.get('body', b''))
            if total > self.max_bytes:
                raise BodyLimitExceeded()
            return message
        async def watched_send(message):
            nonlocal started
            if message['type'] == 'http.response.start':
                started = True
            await send(message)
        try:
            await self.app(scope, limited_receive, watched_send)
        except BodyLimitExceeded:
            if not started:
                await JSONResponse({'detail': 'REQUEST_TOO_LARGE'}, status_code=413)(scope, receive, send)
