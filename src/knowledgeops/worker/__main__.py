import asyncio
import logging

from knowledgeops.config import Settings
from knowledgeops.runtime import Runtime
from knowledgeops.worker.queue import worker_loop


async def main():
    runtime = await Runtime(Settings()).start()
    try:
        await worker_loop(runtime)
    finally:
        await runtime.close()


if __name__ == '__main__':
    logging.basicConfig(level=logging.INFO)
    asyncio.run(main())
