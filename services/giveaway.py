from sqlalchemy.ext.asyncio import AsyncSession
from database.models import Giveaway
from services.checks import add_restriction, get_chat_settings
from services.image_gen import generate_roulette_image
from utils.helpers import deterministic_winners
from datetime import datetime

async def start_giveaway(giveaway: Giveaway, bot):
    text = giveaway.post_text or "🎉 Розыгрыш!"
    if giveaway.post_media:
        msg = await bot.send_photo(giveaway.chat_id, photo=giveaway.post_media, caption=text)
    else:
        msg = await bot.send_message(giveaway.chat_id, text)
    giveaway.post_message_id = msg.message_id
    # Сессия уже сохранена в БД вызывающей стороной

async def check_giveaway_completion(giveaway: Giveaway, bot):
    from database.engine import async_session
    async with async_session() as session:
        if giveaway.mode == 'time' and datetime.utcnow() >= giveaway.end_time:
            await finish_giveaway(giveaway, bot, session)
        elif giveaway.mode == 'participants' and len(giveaway.participants) >= giveaway.max_participants:
            await finish_giveaway(giveaway, bot, session)

async def finish_giveaway(giveaway: Giveaway, bot, session: AsyncSession):
    total = len(giveaway.participants)
    if total == 0:
        return
    winners_idx = deterministic_winners(giveaway.seed, total, giveaway.winner_count)
    giveaway.winners = winners_idx
    giveaway.status = 'finished'
    await session.commit()
    img = generate_roulette_image(winners_idx, total, giveaway.prizes)
    winners_names = [giveaway.participants[i]['username'] for i in winners_idx]
    caption = f"Победители: {', '.join(f'@{u}' for u in winners_names)}"
    await bot.send_photo(giveaway.chat_id, photo=img, caption=caption)
    settings = await get_chat_settings(session, giveaway.chat_id, 'giveaway')
    ban_days = settings.get('ban_days', 7)
    for i in winners_idx:
        p = giveaway.participants[i]
        await add_restriction(session, p['user_id'], p['username'], 'giveaway', days=ban_days)
