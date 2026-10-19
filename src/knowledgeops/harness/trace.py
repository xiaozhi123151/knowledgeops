import asyncio
import logging
import time

logger = logging.getLogger(__name__)


class Trace:
    """Optional metadata-only telemetry; export is isolated from task success."""
    def __init__(self, settings):
        self.client = None
        self.pending = set()
        self.status = 'disabled'
        if settings.langfuse_public_key and settings.langfuse_secret_key.get_secret_value():
            try:
                from langfuse import Langfuse
                self.client = Langfuse(public_key=settings.langfuse_public_key,
                    secret_key=settings.langfuse_secret_key.get_secret_value(),
                    base_url=settings.langfuse_base_url, timeout=1)
                self.status = 'configured_unverified'
            except Exception:
                logger.warning('Langfuse unavailable; continuing without remote trace')
                self.status = 'unavailable'

    def emit(self, name, metadata):
        if not self.client or len(self.pending) >= 32:
            return
        async def send():
            try:
                await asyncio.wait_for(asyncio.to_thread(self._send, name, metadata), timeout=2)
            except Exception:
                logger.warning('Trace export failed; task continues')
        future = asyncio.create_task(send())
        self.pending.add(future)
        future.add_done_callback(self.pending.discard)

    def _send(self, name, metadata):
        with self.client.start_as_current_observation(name=name, as_type='span', metadata=metadata):
            pass

    async def close(self):
        if self.pending:
            await asyncio.gather(*self.pending, return_exceptions=True)

    @staticmethod
    def now():
        return time.perf_counter()
