import datetime
import re
import zoneinfo
import os
from aiogram import Bot, Router, F
from aiogram.types import Message, ChatPermissions
from aiogram.filters import Command
from database import async_session, RouletteSession, RouletteParticipant
from sqlalchemy import select, update, delete
from utils.crypto import generate_provably_fair_round, get_fair_winners
from utils.image_gen import generate_gta_results
from scheduler import scheduler
from config import DEFAULT_TZ

router = Router()
tz_nsk = zoneinfo.ZoneInfo(DEFAULT_TZ)

def mask_username(username: str) -> str:
    uname = username.lstrip('@')
    if len(uname) <= 2:
        return "**"
    return "**" + uname[2:]

async def stop_roulette_action(bot: Bot, chat_id: int):
    async with async_session() as session:
        res = await session.execute(select(RouletteSession).where(RouletteSession.chat_id == chat_id))
        session_data = res.scalar_one_or_none()
        if not session_data or not session_data.is_active:
            return

        p_res = await session.execute(
            select(RouletteParticipant)
            .where(RouletteParticipant.chat_id == chat_id)
            .order_by(RouletteParticipant.id.asc())
        )
        all_parts = p_res.scalars().all()

    valid_participants = [p for p in all_parts if not p.is_disqualified]
    
    await bot.send_message(chat_id, "🛑 СТОП ЗАПИСЬ! Сбор участников завершен. Анализируем данные...")

    masked_chat_list = []
    for idx, p in enumerate(valid_participants, start=1):
        masked_chat_list.append(f"{idx}. {mask_username(p.username)}")

    chat_list_msg = "📋 **Список участников:**\n" + ("\n".join(masked_chat_list) if masked_chat_list else "Участников нет.")
    await bot.send_message(chat_id, chat_list_msg, parse_mode="Markdown")
    
    if session_data.only_list_mode:
        await bot.send_message(chat_id, "🎲 Розыгрыш проводится админом вручную через сторонний рандомайзер под видео!")
        async with async_session() as s:
            await s.execute(delete(RouletteParticipant).where(RouletteParticipant.chat_id == chat_id))
            await s.execute(update(RouletteSession).where(RouletteSession.chat_id == chat_id).values(is_active=False))
            await s.commit()
        return

    winners = get_fair_winners(valid_participants, session_data.winners_count, session_data.seed, session_data.salt)
    
    winner_indices = []
    winner_mentions = []
    for w in winners:
        idx = valid_participants.index(w) + 1
        winner_indices.append(idx)
        winner_mentions.append(f"#{idx} @{w.username}")

    now_nsk = datetime.datetime.now(tz_nsk).strftime("%d.%m.%Y %H:%M:%S")
    img_path = generate_gta_results(winner_indices, len(valid_participants), now_nsk)

    caption = (
        f"🏆 **РЕЗУЛЬТАТЫ РУЛЕТКИ** 🏆\n\n"
        f"Поздравляем победителей:\n" + "\n".join(winner_mentions) + "\n\n"
        f"🔐 **Проверка честности (Provably Fair):**\n"
        f"Seed: `{session_data.seed}`\n"
        f"Salt: `{session_data.salt}`\n"
        f"SHA-256 хэш раунда (был известен до старта):\n`{session_data.sha_hash}`"
    )

    if os.path.exists(img_path):
        from aiogram.types import FSInputFile
        await bot.send_photo(chat_id, photo=FSInputFile(img_path), caption=caption, parse_mode="Markdown")
        try:
            os.remove(img_path)
        except:
            pass
    else:
        await bot.send_message(chat_id, caption, parse_mode="Markdown")

    for p in all_parts:
        if p.is_disqualified:
            try:
                await bot.restrict_chat_member(
                    chat_id=chat_id,
                    user_id=p.user_id,
                    permissions=ChatPermissions(can_send_messages=True, can_use_inline_bots=True)
                )
            except Exception:
                pass

    async with async_session() as s:
        await s.execute(delete(RouletteParticipant).where(RouletteParticipant.chat_id == chat_id))
        await s.execute(update(RouletteSession).where(RouletteSession.chat_id == chat_id).values(is_active=False))
        await s.commit()

@router.message(Command("рулетка"))
@router.message(F.text.startswith("@рулетка"))
async def start_roulette_cmd(message: Message, bot: Bot):
    member = await bot.get_chat_member(message.chat.id, message.from_user.id)
    if member.status not in ["administrator", "creator"]:
        return 

    text = message.text.replace("@рулетка", "").strip()
    
    p_match = re.search(r'(\d+)п', text)
    winners_count = int(p_match.group(1)) if p_match else 1
    only_list_mode = False if p_match else True

    delay_minutes = 5 
    
    seed, salt, sha_hash = generate_provably_fair_round()
    
    # Принудительно выставляем часовой пояс Новосибирска для корректной работы на зарубежном сервере
    stop_time = datetime.datetime.now(tz_nsk) + datetime.timedelta(minutes=delay_minutes)

    async with async_session() as session:
        # Для БД убираем инфо о таймзоне, чтобы SQLite не ругалась
        await session.merge(RouletteSession(
            chat_id=message.chat.id,
            is_active=True,
            trigger_symbol="+",
            winners_count=winners_count,
            stop_time=stop_time.replace(tzinfo=None),
            seed=seed,
            salt=salt,
            sha_hash=sha_hash,
            only_list_mode=only_list_mode
        ))
        await session.commit()

    start_msg = (
        f"🎰 **СТАРТ РУЛЕТКИ!** 🎰\n\n"
        f"Отправьте ровно один символ `+` для участия!\n"
        f"⏱ Запись закроется через {delay_minutes} мин.\n"
        f"Количество победителей: {'Вручную админом' if only_list_mode else winners_count}\n\n"
        f"🔐 **Хэш честности раунда (SHA-256):** \n`{sha_hash}`"
    )
    await message.answer(start_msg, parse_mode="Markdown")

    scheduler.add_job(
        stop_roulette_action,
        'date',
        run_date=stop_time,
        args=[bot, message.chat.id],
        id=f"roulette_{message.chat.id}",
        replace_existing=True
    )

@router.message(F.chat.type.in_({"group", "supergroup"}))
async def handle_chat_messages(message: Message, bot: Bot):
    if not message.text:
        return

    # КРИТИЧЕСКИЙ ФИКС: Проверяем, является ли отправитель админом чата
    user_member = await bot.get_chat_member(message.chat.id, message.from_user.id)
    is_admin = user_member.status in ["administrator", "creator"]

    async with async_session() as session:
        res = await session.execute(select(RouletteSession).where(RouletteSession.chat_id == message.chat.id))
        session_data = res.scalar_one_or_none()
        
        if not session_data or not session_data.is_active:
            return

        user = message.from_user
        text_clean = message.text.strip()

        p_res = await session.execute(
            select(RouletteParticipant)
            .where(RouletteParticipant.chat_id == message.chat.id, RouletteParticipant.user_id == user.id)
        )
        participant = p_res.scalar_one_or_none()

        if text_clean == session_data.trigger_symbol:
            # Админы не участвуют в рулетке по плюсу, их сообщения просто остаются как текст
            if is_admin:
                return

            if not user.username:
                await message.reply(
                    "⚠️ Для участия в рулетке вам необходимо установить **username** в настройках профиля!"
                )
                return

            if participant:
                if not participant.is_disqualified:
                    await session.execute(
                        update(RouletteParticipant)
                        .where(RouletteParticipant.id == participant.id)
                        .values(is_disqualified=True)
                    )
                    await session.commit()
                    await message.answer(f"🚫 Игрок @{user.username} отправил '+' повторно! Дисквалификация.")
                    try:
                        await bot.restrict_chat_member(message.chat.id, user.id, ChatPermissions(can_send_messages=False))
                    except Exception: pass
                await message.delete()
                return
            else:
                session.add(RouletteParticipant(
                    chat_id=message.chat.id,
                    username=user.username,
                    user_id=user.id,
                    msg_count=0
                ))
                await session.commit()
                return

        else:
            # Если пишет НЕ плюс: админские сообщения ИГНОРИРУЕМ (оставляем), обычные — УДАЛЯЕМ
            if is_admin:
                return

            await message.delete() 
            
            if participant:
                new_count = participant.msg_count + 1
                if new_count >= 2:
                    await session.execute(
                        update(RouletteParticipant)
                        .where(RouletteParticipant.id == participant.id)
                        .values(msg_count=new_count, is_disqualified=True)
                    )
                    await session.commit()
                    await message.answer(f"🚫 Игрок @{user.username} нарушил правила общения! Мут.")
                    try:
                        await bot.restrict_chat_member(message.chat.id, user.id, ChatPermissions(can_send_messages=False))
                    except Exception: pass
                else:
                    await session.execute(
                        update(RouletteParticipant)
                        .where(RouletteParticipant.id == participant.id)
                        .values(msg_count=new_count)
                    )
                    await session.commit()
