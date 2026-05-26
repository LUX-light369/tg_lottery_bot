import datetime
import re
import zoneinfo
import os
from aiogram import Bot, Router, F
from aiogram.types import Message, ChatPermissions, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.filters import Command
from database import async_session, RouletteSession, RouletteParticipant
from sqlalchemy import select, update, delete
from utils.crypto import generate_provably_fair_round, get_fair_winners
from utils.image_gen import generate_gta_results
from scheduler import scheduler
from config import DEFAULT_TZ, ADMIN_ID

router = Router()
tz_nsk = zoneinfo.ZoneInfo(DEFAULT_TZ)

def mask_username(username: str) -> str:
    uname = username.lstrip('@')
    if len(uname) <= 2:
        return "**"
    return "**" + uname[2:]

async def is_valid_admin_team(bot: Bot, chat_id: int, user_id: int) -> bool:
    try:
        chat_admins = await bot.get_chat_administrators(chat_id)
        admin_ids = [admin.user.id for admin in chat_admins]
        if ADMIN_ID not in admin_ids:
            return False
        if user_id in admin_ids:
            return True
    except Exception:
        pass
    return False

# --- ВЫЗОВ СТОПА РУЛЕТКИ ---
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
    
    await bot.send_message(chat_id, "🛑 **СТОП ЗАПИСЬ!** Сбор участников завершен. Анализируем данные...")

    masked_chat_list = []
    for idx, p in enumerate(valid_participants, start=1):
        masked_chat_list.append(f"{idx}. {mask_username(p.username)}")

    chat_list_msg = "📋 **Список участников:**\n" + ("\n".join(masked_chat_list) if masked_chat_list else "Участников нет.")
    await bot.send_message(chat_id, chat_list_msg, parse_mode="Markdown")
    
    if session_data.only_list_mode:
        await bot.send_message(chat_id, "🎲 Розыгрыш проводится админом вручную через рандомайзер!")
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
        f"🏆 **РЕЗУЛЬТАТЫ РОЗЫГРЫША** 🏆\n\n"
        f"Поздравляем победителей:\n" + "\n".join(winner_mentions) + "\n\n"
        f"🔐 **Provably Fair:**\n"
        f"Seed: `{session_data.seed}`\n"
        f"SHA-256 хэш раунда:\n`{session_data.sha_hash}`"
    )

    if os.path.exists(img_path):
        from aiogram.types import FSInputFile
        await bot.send_photo(chat_id, photo=FSInputFile(img_path), caption=caption, parse_mode="Markdown")
        try: os.remove(img_path)
        except: pass
    else:
        await bot.send_message(chat_id, caption, parse_mode="Markdown")

    async with async_session() as s:
        await s.execute(delete(RouletteParticipant).where(RouletteParticipant.chat_id == chat_id))
        await s.execute(update(RouletteSession).where(RouletteSession.chat_id == chat_id).values(is_active=False))
        await s.commit()

# --- ФУНКЦИЯ ДЛЯ ЗАПУСКА ИЗ АДМИНКИ ---
async def start_custom_roulette(bot: Bot, chat_id: int, mode: str, limit_val: int, winners_count: int, link: str = None) -> bool:
    async with async_session() as session:
        res = await session.execute(select(RouletteSession).where(RouletteSession.chat_id == chat_id))
        active_session = res.scalar_one_or_none()
        if active_session and active_session.is_active:
            return False # У чата уже есть активный раунд

        seed, salt, sha_hash = generate_provably_fair_round()
        
        # Если режим по времени, вычисляем стоп-тайм
        stop_time = None
        if mode == "time":
            stop_time = datetime.datetime.now(tz_nsk) + datetime.timedelta(minutes=limit_val)

        new_session = RouletteSession(
            chat_id=chat_id,
            is_active=True,
            trigger_symbol="+",
            winners_count=winners_count,
            stop_time=stop_time.replace(tzinfo=None) if stop_time else None,
            seed=seed,
            salt=salt,
            sha_hash=sha_hash,
            only_list_mode=False
        )
        await session.merge(new_session)
        await session.commit()

    # Формируем красивую клавиатуру с заданием
    builder = InlineKeyboardBuilder()
    if link:
        builder.button(text="🔗 Выполнить задание (Подписаться)", url=link)
    builder.adjust(1)

    start_msg = (
        f"🎰 **НОВЫЙ РОЗЫГРЫШ ЗАПУЩЕН!** 🎰\n\n"
        f"Для участия отправьте ровно один символ `+` в этот чат!\n"
        f"🏆 Победителей: `{winners_count}`\n"
    )
    if mode == "time":
        start_msg += f"⏱ Запись закроется автоматически через: `{limit_val} мин.`\n"
    else:
        start_msg += f"👥 Режим: Набор до `{limit_val} участников`\n"
        
    if link:
        start_msg += f"\n⚠️ **Внимание:** Перед отправкой `+` обязательно выполните задание по кнопке ниже!"

    start_msg += f"\n\n🔐 **SHA-256 Хэш честности (Provably Fair):**\n`{sha_hash}`"

    await bot.send_message(chat_id, start_msg, reply_markup=builder.as_markup() if link else None, parse_mode="Markdown")

    # Если по времени — вешаем задачу в планировщик (БЕЗ использования даты в БД)
    if mode == "time" and stop_time:
        scheduler.add_job(
            stop_roulette_action,
            'date',
            run_date=stop_time,
            args=[bot, chat_id],
            id=f"roulette_{chat_id}",
            replace_existing=True
        )
    return True

# --- СТАНДАРТНЫЙ ВЫЗОВ В ЧАТЕ ЧЕРЕЗ @рулетка ---
@router.message(Command("рулетка"))
@router.message(F.text.startswith("@рулетка"))
async def start_roulette_cmd(message: Message, bot: Bot):
    if not await is_valid_admin_team(bot, message.chat.id, message.from_user.id):
        return 

    text = message.text.replace("@рулетка", "").strip()
    p_match = re.search(r'(\d+)п', text)
    winners_count = int(p_match.group(1)) if p_match else 1
    
    # По умолчанию для быстрой команды ставим 5 минут
    success = await start_custom_roulette(bot, message.chat.id, "time", 5, winners_count)

# --- ОБРАБОТЧИК ДЛЯ ПЛЮСОВ И ФЛУДА ---
@router.message(F.chat.type.in_({"group", "supergroup"}))
async def handle_chat_messages(message: Message, bot: Bot):
    if not message.text: return

    async with async_session() as session:
        res = await session.execute(select(RouletteSession).where(RouletteSession.chat_id == message.chat.id))
        session_data = res.scalar_one_or_none()
        
        if not session_data or not session_data.is_active: return

        try:
            chat_admins = await bot.get_chat_administrators(message.chat.id)
            admin_ids = [admin.user.id for admin in chat_admins]
            is_admin = message.from_user.id in admin_ids
        except Exception: is_admin = False

        user = message.from_user
        text_clean = message.text.strip()

        p_res = await session.execute(
            select(RouletteParticipant)
            .where(RouletteParticipant.chat_id == message.chat.id, RouletteParticipant.user_id == user.id)
        )
        participant = p_res.scalar_one_or_none()

        if text_clean == session_data.trigger_symbol:
            if is_admin: return 

            if not user.username:
                await message.reply("⚠️ Для участия установите **username** в профиле Telegram!")
                return

            if participant:
                if not participant.is_disqualified:
                    await session.execute(update(RouletteParticipant).where(RouletteParticipant.id == participant.id).values(is_disqualified=True))
                    await session.commit()
                    await message.answer(f"🚫 Игрок @{user.username} дисквалифицирован за повторный +.")
                    try: await bot.restrict_chat_member(message.chat.id, user.id, ChatPermissions(can_send_messages=False))
                    except Exception: pass
                await message.delete()
                return
            else:
                # Регистрируем участника
                session.add(RouletteParticipant(chat_id=message.chat.id, username=user.username, user_id=user.id, msg_count=0))
                await session.commit()
                
                # Проверяем, если режим по кол-ву участников превысил лимит
                # Считаем общее число участников
                count_res = await session.execute(select(RouletteParticipant).where(RouletteParticipant.chat_id == message.chat.id))
                total_parts = len(count_res.scalars().all())
                
                # Если стоп-тайма нет, значит режим по участникам
                if session_data.stop_time is None and total_parts >= session_data.winners_count * 5: # Или жесткое ограничение
                     pass # Логика динамического лимита участников
                return

        else:
            if is_admin: return
            await message.delete() 
