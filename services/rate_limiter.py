import asyncio
from collections import defaultdict
from config import MSG_DELAY

class RateLimiter:
    def __init__(self):
        self.last_sent = defaultdict(float)

    async def wait(self, chat_id: int):
        now = asyncio.get_event_loop().time()
        diff = now - self.last_sent[chat_id]
        if diff < MSG_DELAY:
            await asyncio.sleep(MSG_DELAY - diff)
        self.last_sent[chat_id] = asyncio.get_event_loop().time()

rate_limiter = RateLimiter()
