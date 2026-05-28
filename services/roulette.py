from datetime import datetime, timedelta
from services.checks import add_restriction, get_chat_settings
from services.image_gen import generate_roulette_image
from utils.helpers import deterministic_winners
from database.models import Roulette
from sqlalchemy import select
from config import MAIN_ADMIN_ID
from services.rate_limiter import rate_limiter

async def start_recording(roulette, bot):
    async with await bot.session() as session:
        settings = await get_chat_settings(session, roulette.chat_id, 'roulette')
    start_text = settings.get('start_message', 'Рулетка началась! Пишите "+"')
    msg = await bot.send_message(roulette.chat_id, start_text)
    roulette.start_message_id = msg.message_id
    roulette.status = 'active'
    # Обновляем в БД
    async with await bot.session() as session:
        session.add(roulette)
        await session.commit()
    # Планируем остановку
    await schedule_roulette_stop(roulette, bot)

async def finish_roulette(roulette_id, bot):
    async with await bot.session() as session:
        stmt = select(Roulette).where(Roulette.id == roulette_id)
        res = await session.execute(stmt)
        roulette = res.scalars().first()
        if not roulette or roulette.status != 'active':
            return
        # Фильтруем участников
        valid = []
        for p in roulette.participants:
            try:
                user = await bot.get_chat(p['user_id'])
                if user.username:
                    valid.append(p)
            except:
                pass
        roulette.participants = valid
        await session.commit()

        # Список админу (с @)
        admin_list = "\n".join(f"@{p['username']}" for p in valid)
        for admin_id in {roulette.creator_id, MAIN_ADMIN_ID}:
            try:
                await bot.send_message(admin_id, f"Участники рулетки:\n{admin_list}")
            except:
                pass
        # Список в чат (без @)
        chat_list = ", ".join(p['username'] for p in valid)
        await bot.send_message(roulette.chat_id, f"Участники: {chat_list}")

        if roulette.winner_count > 0:
            winners_idx = deterministic_winners(roulette.seed, len(valid), roulette.winner_count)
            roulette.winners = winners_idx
            await session.commit()
            settings = await get_chat_settings(session, roulette.chat_id, 'roulette')
            img = generate_roulette_image(winners_idx, len(valid), roulette.prizes)
            caption = settings.get('winner_message', 'Победители: {winners}')
            winners_str = ", ".join(f"@{valid[i]['username']}" for i in winners_idx)
            caption = caption.format(winners=winners_str)
            await bot.send_photo(roulette.chat_id, photo=img, caption=caption)
            # Ограничения
            ban_days = settings.get('ban_days', 7)
            for i in winners_idx:
                await add_restriction(session, valid[i]['user_id'], valid[i]['username'], 'roulette', days=ban_days)
        else:
            await bot.send_message(roulette.chat_id, "Запись окончена. Админ выберет победителей вручную.")
        # Стоп-сообщение
        stop_text = settings.get('stop_message', 'Рулетка завершена.')
        await bot.send_message(roulette.chat_id, stop_text)
        roulette.status = 'finished'
        await session.commit()
        # Размут
        for uid in roulette.muted_users:
            try:
                await bot.restrict_chat_member(roulette.chat_id, uid, can_send_messages=True)
            except:
                pass
