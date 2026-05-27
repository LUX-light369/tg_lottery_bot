import asyncio
from typing import Any, Callable, Dict, Awaitable
from aiogram import BaseMiddleware
from aiogram.types import Message

class AntiFloodMiddleware(BaseMiddleware):
    def __init__(self, delay: float = 2.0) -> None:
        self.delay = delay
        self.last_sent = {}
        super().__init__()

    async def __call__(
        self,
        handler: Callable[[Message, Dict[str, Any]], Awaitable[Any]],
        event: Message,
        data: Dict[str, Any]
    ) -> Any:
        if not event.text:
            return await handler(event, data)
            
        user_id = event.from_user.id
        now = asyncio.get_event_loop().time()
        
        # Ограничиваем системные ответы бота в группах
        if event.chat.type in {"group", "supergroup"}:
            if user_id in self.last_sent:
                if now - self.last_sent[user_id] < self.delay:
                    return # Молча дропаем слишком частые триггеры
            self.last_sent[user_id] = now
            
        return await handler(event, data)
