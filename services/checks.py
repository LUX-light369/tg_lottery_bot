from sqlalchemy import select, or_
from database.models import Restriction, ChatSettings
from datetime import datetime
from typing import Optional

async def is_admin(bot, chat_id: int, user_id: int) -> bool:
    try:
        member = await bot.get_chat_member(chat_id, user_id)
        return member.status in ("administrator", "creator")
    except:
        return False

async def is_main_admin(user_id: int) -> bool:
    from config import MAIN_ADMIN_ID
    return user_id == MAIN_ADMIN_ID

async def has_username(user) -> bool:
    return user.username is not None

async def check_subscription(bot, channel_username: str, user_id: int) -> bool:
    try:
        member = await bot.get_chat_member(channel_username, user_id)
        return member.status in ("member", "administrator", "creator")
    except:
        return False

async def is_restricted(session, user_id: int, module: str) -> bool:
    now = datetime.utcnow()
    stmt = select(Restriction).where(
        Restriction.user_id == user_id,
        Restriction.module == module,
        or_(Restriction.restricted_until == None, Restriction.restricted_until > now)
    )
    res = await session.execute(stmt)
    return res.scalars().first() is not None

async def add_restriction(session, user_id: int, username: Optional[str], module: str, days: Optional[int] = None):
    from datetime import timedelta
    until = datetime.utcnow() + timedelta(days=days) if days else None
    r = Restriction(user_id=user_id, username=username, module=module, restricted_until=until)
    session.add(r)
    await session.commit()

async def get_chat_settings(session, chat_id: int, module: str) -> dict:
    stmt = select(ChatSettings).where(ChatSettings.chat_id == chat_id, ChatSettings.module == module)
    result = await session.execute(stmt)
    settings = result.scalars().first()
    return settings.data if settings else {}
