from aiogram import Router, F, Bot
from aiogram.types import Message
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from database.models import Roulette
from services.checks import is_admin, has_username, get_chat_settings
from services.roulette import start_recording, finish_roulette
from services.rate_limiter import rate_limiter
from utils.helpers import generate_seed, get_md5_hash, deterministic_winners
from datetime import datetime, timedelta
import re

router = Router()

# @рулетка [Nп] [время]
@router.message(F.text.regexp(r"^@рулетка(?:\s+(\d+п?))?(?:\s+(\d{2}:\d{2}))?"))
async def roulette_command(message: Message, bot: Bot, session: AsyncSession):
    await rate_limiter.wait(message.chat.id)
    if not await is_admin(bot, message.chat.id, message.from_user.id):
        await message.reply("Только администратор может запускать рулетку.")
        return
    match = re.match(r"^@рулетка(?:\s+(\d+п?))?(?:\s+(\d{2}:\d{2}))?", message.text)
    winner_str = match.group(1)  # "3п" или "3"
    time_str = match.group(2)    # "20:00"
    winner_count = int(winner_str.replace("п", "")) if winner_str else None

    settings = await get_chat_settings(session, message.chat.id, 'roulette')
    if not settings:
        await message.reply("Сначала настройте рулетку через /settings в личке у главного админа.")
        return
    prizes = settings.get('prizes', ['Приз'])
    if winner_count and winner_count > len(prizes):
        await message.reply(f"Победителей ({winner_count}) больше, чем призов ({len(prizes)}). Обновите список призов.")
        return
    if not winner_count:
        winner_count = settings.get('default_winners', 1)

    roulette = Roulette(
        chat_id=message.chat.id,
        creator_id=message.from_user.id,
        status='scheduled',
        winner_count=winner_count,
        prizes=prizes[:winner_count],
        duration_minutes=settings.get('duration', 5),
        trigger_list=settings.get('triggers', ['+']),
        start_at=None
    )
    seed = generate_seed()
    roulette.seed = seed
    roulette.seed_hash = get_md5_hash(seed)

    if time_str:
        now = datetime.now()
        hour, minute = map(int, time_str.split(":"))
        start_time = now.replace(hour=hour, minute=minute, second=0, microsecond=0)
        if start_time < now:
            start_time += timedelta(days=1)
        roulette.start_at = start_time
        info = (f"🎰 Рулетка запланирована\n"
                f"Победителей: {roulette.winner_count}\n"
                f"Призы: {', '.join(roulette.prizes)}\n"
                f"Начало в {time_str}\n"
                f"Длительность записи: {roulette.duration_minutes} мин\n"
                f"Триггер: {', '.join(roulette.trigger_list)}")
        await message.answer(info)
        session.add(roulette)
        await session.commit()
        # Планируем отложенный запуск
        from services.scheduler import scheduler
        from apscheduler.triggers.date import DateTrigger
        async def delayed_start():
            from database.engine import async_session as a_s
            async with a_s() as s:
                r = await s.get(Roulette, roulette.id)
                await start_recording(r, bot)
        scheduler.add_job(delayed_start, trigger=DateTrigger(run_date=start_time), id=f"roulette_start_{roulette.id}")
    else:
        roulette.status = 'active'
        session.add(roulette)
        await session.commit()
        await start_recording(roulette, bot)

# Триггеры во время активной рулетки
@router.message(F.text)
async def handle_triggers(message: Message, bot: Bot, session: AsyncSession):
    stmt = select(Roulette).where(
        Roulette.chat_id == message.chat.id,
        Roulette.status == 'active'
    )
    result = await session.execute(stmt)
    roulette = result.scalars().first()
    if not roulette:
        return
    if message.text in roulette.trigger_list:
        # Проверка на повтор
        if message.from_user.id in [p['user_id'] for p in roulette.participants]:
            await message.delete()
            try:
                await bot.restrict_chat_member(message.chat.id, message.from_user.id, can_send_messages=False)
            except:
                pass
            roulette.muted_users.append(message.from_user.id)
            roulette.participants = [p for p in roulette.participants if p['user_id'] != message.from_user.id]
            await session.commit()
            return
        if not await has_username(message.from_user):
            await message.reply("У вас отсутствует @username. Установите его в настройках Telegram для участия.", quote=True)
            await message.delete()
            return
        # Добавляем участника
        roulette.participants.append({"user_id": message.from_user.id, "username": message.from_user.username})
        await session.commit()
        await message.delete()
    else:
        await message.delete()

# Перекрут рулетки
@router.message(F.text.regexp(r"^@перекрут(?:\s+(\d+п?(?:,\d+п?)*))"))
async def reroll_roulette(message: Message, bot: Bot, session: AsyncSession):
    await rate_limiter.wait(message.chat.id)
    if not await is_admin(bot, message.chat.id, message.from_user.id):
        await message.reply("Только администратор может выполнить перекрут.")
        return
    match = re.match(r"^@перекрут(?:\s+(\d+п?(?:,\d+п?)*))", message.text)
    if not match:
        await message.reply("Неверный формат. Пример: @перекрут 1п,3п")
        return
    winners_str = match.group(1)
    exclude_ids = [int(s.replace("п","")) for s in winners_str.split(",")]
    # Ищем последнюю завершённую рулетку
    stmt = select(Roulette).where(Roulette.chat_id == message.chat.id, Roulette.status == 'finished').order_by(Roulette.created_at.desc()).limit(1)
    res = await session.execute(stmt)
    roulette = res.scalars().first()
    if not roulette:
        await message.reply("Нет завершённой рулетки для перекрута.")
        return
    valid = []
    for p in roulette.participants:
        try:
            user = await bot.get_chat(p['user_id'])
            if user.username:
                valid.append(p)
        except:
            pass
    if not valid:
        await message.reply("Нет участников.")
        return
    old_winner_indices = set(roulette.winners)
    exclude_indices = [i-1 for i in exclude_ids if 1 <= i <= len(valid)]
    new_winners = deterministic_winners(roulette.seed, len(valid), roulette.winner_count, exclude=list(old_winner_indices) + exclude_indices)
    roulette.winners = new_winners
    await session.commit()
    from services.image_gen import generate_roulette_image
    img = generate_roulette_image(new_winners, len(valid), roulette.prizes)
    winners_names = [valid[i]['username'] for i in new_winners]
    caption = f"🔄 Перекрут. Новые победители: {', '.join(f'@{u}' for u in winners_names)}"
    await bot.send_photo(message.chat.id, photo=img, caption=caption)
