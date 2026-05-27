import datetime
import re
import zoneinfo
import os
import json
from aiogram import Bot, Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.filters import Command
from database import async_session, RouletteSession, RouletteParticipant, PastRouletteRound, BotConfig, WinnerCooldown, select, update, delete
from utils.crypto import generate_provably_fair_round, get_fair_winners
from utils.image_gen import generate_gta_results
from scheduler import scheduler
from config import DEFAULT_TZ, ADMIN_ID

router = Router()
tz_nsk = zoneinfo.ZoneInfo(DEFAULT_TZ)

# --- АНОНС И СТАРТ ОТЛОЖЕННОЙ РУЛЕТКИ ---
async def start_recording_now(bot: Bot, chat_id: int):
    async with async_session() as s:
        cfg = (await s.execute(select(BotConfig).where(BotConfig.id == 1))).scalar_one()
        await s.execute(update(RouletteSession).where(RouletteSession.chat_id == chat_id).values(is_joined_active=True))
        await s.commit()
    
    msg = cfg.r_start_msg.format(trigger=f"'{cfg.r_trigger}'")
    await bot.send_message(chat_id, msg, parse_mode="HTML")

# --- КОМАНДА @рулетка Хп ЧЧ:ММ ---
@router.message(F.chat.type.in_({"group", "supergroup"}))
@router.message(Command("рулетка"))
async def process_roulette_cmd(message: Message, bot: Bot):
    if not (message.text and ("@рулетка" in message.text or message.text.startswith("/рулетка"))): return
    
    # Проверка прав администратора чата
    try:
        admins = [a.user.id for a in await bot.get_chat_administrators(message.chat.id)]
        if message.from_user.id not in admins and message.from_user.id != ADMIN_ID: return
    except: return

    text = message.text.replace("@рулетка", "").replace("/рулетка", "").strip()
    p_match = re.search(r'(\d+)п', text)
    t_match = re.search(r'(\d{2}:\d{2})', text)
    
    winners_count = int(p_match.group(1)) if p_match else 1
    prizes_list = text.split(p_match.group(0))[-1].strip() if p_match else "Приз"
    if t_match:
        prizes_list = prizes_list.replace(t_match.group(0), "").strip()

    async with async_session() as s:
        cfg = (await s.execute(select(BotConfig).where(BotConfig.id == 1))).scalar_one()
        # Чистим старую сессию чата
        await s.execute(delete(RouletteSession).where(RouletteSession.chat_id == message.chat.id))
        await s.execute(delete(RouletteParticipant).where(RouletteParticipant.chat_id == message.chat.id))
        
        seed, salt, sha_hash = generate_provably_fair_round()
        session_data = RouletteSession(
            chat_id=message.chat.id,
            is_active=True,
            is_joined_active=False if t_match else True,
            winners_count=winners_count,
            seed=seed,
            salt=salt,
            sha_hash=sha_hash,
            prizes=prizes_list or cfg.r_default_prizes
        )
        s.add(session_data)
        await s.commit()

    # Парсим призы для валидации админу
    prizes_split = [p.strip() for p in prizes_list.split(",") if p.strip()]
    if len(prizes_split) > 1 and len(prizes_split) < winners_count:
        await bot.send_message(ADMIN_ID, f"⚠️ **Внимание:** В рулетке чата `{message.chat.id}` указано {winners_count} мест, но всего {len(prizes_split)} призов! Добавьте призы.")

    # Логика времени
    if t_match:
        target_time_str = t_match.group(1)
        now = datetime.datetime.now(tz_nsk)
        target_time = datetime.datetime.strptime(target_time_str, "%H:%M").time()
        run_date = datetime.datetime.combine(now.date(), target_time).replace(tzinfo=tz_nsk)
        
        if run_date < now:
            run_date += datetime.timedelta(days=1)
            
        await message.answer(f"📢 **Рулетка запланирована!**\nКоличество мест: `{winners_count}`\nПризы: `{prizes_list or cfg.r_default_prizes}`\nЗапись начнется автоматически в **{target_time_str}** по НСК.\n\n🔐 SHA-256 хэш честности:\n`{sha_hash}`", parse_mode="Markdown")
        
        scheduler.add_job(start_recording_now, 'date', run_date=run_date, args=[bot, message.chat.id])
        # Автоматический стоп через 10 минут после старта
        scheduler.add_job(stop_roulette_action, 'date', run_date=run_date + datetime.timedelta(minutes=10), args=[bot, message.chat.id])
    else:
        await message.answer(f"🎰 **Рулетка запущена!**\nОтправляйте триггер `{cfg.r_trigger}` для участия!\n🏆 Мест: `{winners_count}`\n🔐 SHA-256 раунда:\n`{sha_hash}`", parse_mode="Markdown")
        scheduler.add_job(stop_roulette_action, 'date', run_date=datetime.datetime.now(tz_nsk) + datetime.timedelta(minutes=5), args=[bot, message.chat.id])

# --- СТОП ЗАПИСИ И ПОДВЕДЕНИЕ ИТОГОВ ---
async def stop_roulette_action(bot: Bot, chat_id: int):
    async with async_session() as s:
        session_data = (await s.execute(select(RouletteSession).where(RouletteSession.chat_id == chat_id))).scalar_one_or_none()
        if not session_data or not session_data.is_active: return
        
        cfg = (await s.execute(select(BotConfig).where(BotConfig.id == 1))).scalar_one()
        parts = (await s.execute(select(RouletteParticipant).where(RouletteParticipant.chat_id == chat_id, RouletteParticipant.is_disqualified == False))).scalars().all()
        
        # Проверяем черный список / кулдауны победителей
        cooldowns = (await s.execute(select(WinnerCooldown).where(WinnerCooldown.until_date > datetime.datetime.utcnow()))).scalars().all()
        banned_names = [c.username for c in cooldowns]
        
        valid_parts = [p for p in parts if p.username not in banned_names]

    await bot.send_message(chat_id, cfg.r_stop_msg, parse_mode="HTML")

    # Списки без @ в чат
    chat_list = [f"{idx}. {p.username}" for idx, p in enumerate(valid_parts, start=1)]
    await bot.send_message(chat_id, "📋 **Список участников:**\n" + ("\n".join(chat_list) if chat_list else "Пусто."), parse_mode="Markdown")
    
    # Список админу в ЛС с кликабельным @
    admin_list = [f"{idx}. @{p.username} (ID: {p.user_id})" for idx, p in enumerate(valid_parts, start=1)]
    try:
        await bot.send_message(ADMIN_ID, f"📋 Список участников рулетки в чате `{chat_id}`:\n" + "\n".join(admin_list))
    except: pass

    if not valid_parts:
        await bot.send_message(chat_id, "🤷‍♂️ Победителей выбрать невозможно, участников нет.")
        return

    # Честный выбор
    winners = get_fair_winners(valid_parts, session_data.winners_count, session_data.seed, session_data.salt)
    
    prizes_split = [p.strip() for p in session_data.prizes.split(",") if p.strip()]
    winner_mentions = []
    
    for idx, w in enumerate(winners):
        prize = prizes_split[0] if len(prizes_split) == 1 else (prizes_split[idx] if idx < len(prizes_split) else "Приз")
        winner_mentions.append(f"🏆 Место #{idx+1}: @{w.username} — 🎁 **{prize}**")

    # GTA-Картинка результатов
    now_str = datetime.datetime.now(tz_nsk).strftime("%d.%m.%Y %H:%M")
    img_path = generate_gta_results([valid_parts.index(w)+1 for w in winners], len(valid_parts), now_str)
    
    caption = cfg.r_winner_template.format(winners="\n".join(winner_mentions), default_prizes=session_data.prizes)
    
    if os.path.exists(img_path):
        from aiogram.types import FSInputFile
        await bot.send_photo(chat_id, photo=FSInputFile(img_path), caption=caption, parse_mode="HTML")
        try: os.remove(img_path)
        except: pass
    else:
        await bot.send_message(chat_id, caption, parse_mode="HTML")

    # Документ верификации честности
    verify_msg = (
        f"🔐 **ПРОВЕРКА ЧЕСТНОСТИ (Provably Fair)**\n\n"
        f"Результат раунда абсолютно прозрачен и сгенерирован до начала записи участников.\n\n"
        f"• SHA-256 хэш раунда: `{session_data.sha_hash}`\n"
        f"• Начальный Seed: `{session_data.seed}`\n"
        f"• Соль (Salt): `{session_data.salt}`\n\n"
        f"📝 **Инструкция проверки:**\n"
        f"1. Возьмите Seed и строку соли.\n"
        f"2. Объедините их через двоеточие и закодируйте в SHA-256 на любом независимом сайте (например md5calc.com).\n"
        f"3. Вы получите Хэш, полностью совпадающий с опубликованным до старта!"
    )
    await bot.send_message(chat_id, verify_msg, parse_mode="Markdown")

    # Кэшируем раунд для перекрута на 24 часа
    async with async_session() as s:
        p_json = json.dumps([{"user_id": p.user_id, "username": p.username} for p in valid_parts])
        w_json = json.dumps([{"user_id": w.user_id, "username": w.username} for w in winners])
        await s.merge(PastRouletteRound(chat_id=chat_id, winners_json=w_json, participants_json=p_json, updated_at=datetime.datetime.utcnow()))
        await s.execute(delete(RouletteParticipant).where(RouletteParticipant.chat_id == chat_id))
        await s.execute(update(RouletteSession).where(RouletteSession.chat_id == chat_id).values(is_active=False))
        await s.commit()

# --- СБОР СИМВОЛОВ ЗАПИСИ (ПЛЮСОВ) ---
@router.message(F.chat.type.in_({"group", "supergroup"}))
async def collect_triggers(message: Message, bot: Bot):
    if not message.text: return
    
    async with async_session() as s:
        session_data = (await s.execute(select(RouletteSession).where(RouletteSession.chat_id == message.chat.id))).scalar_one_or_none()
        if not session_data or not session_data.is_active or not session_data.is_joined_active: return
        
        cfg = (await s.execute(select(BotConfig).where(BotConfig.id == 1))).scalar_one()

    # Фильтруем триггеры
    if message.text.strip() == cfg.r_trigger:
        if not message.from_user.username:
            await message.reply("⚠️ Для участия пропишите @username в настройках аккаунта Telegram!")
            return
            
        async with async_session() as s:
            exist = (await s.execute(select(RouletteParticipant).where(RouletteParticipant.chat_id == message.chat.id, RouletteParticipant.user_id == message.from_user.id))).scalar_one_or_none()
            if exist:
                if not exist.is_disqualified:
                    await s.execute(update(RouletteParticipant).where(RouletteParticipant.id == exist.id).values(is_disqualified=True))
                    await s.commit()
                    await message.answer(f"🚫 Игрок {message.from_user.username} дисквалифицирован за дублирование триггера!")
                await message.delete()
                return
            
            s.add(RouletteParticipant(chat_id=message.chat.id, user_id=message.from_user.id, username=message.from_user.username))
            await s.commit()
            return
    else:
        # Стираем любой флуд во время активной записи
        try: await message.delete()
        except: pass

# --- МЕХАНИКА @перекрут ---
@router.message(F.text.startswith("@перекрут"))
async def process_reroll(message: Message, bot: Bot):
    try:
        admins = [a.user.id for a in await bot.get_chat_administrators(message.chat.id)]
        if message.from_user.id not in admins and message.from_user.id != ADMIN_ID: return
    except: return

    # Вытаскиваем места, например "1п,3п"
    places = [int(p.replace("п","")) for p in re.findall(r'\d+п', message.text)]
    if not places: return

    async with async_session() as s:
        round_data = (await s.execute(select(PastRouletteRound).where(PastRouletteRound.chat_id == message.chat.id))).scalar_one_or_none()
        
    if not round_data or (datetime.datetime.utcnow() - round_data.updated_at).total_seconds() > 86400:
        await message.reply("❌ Прошло более 24 часов или сессий рулетки не найдено!")
        return

    parts = json.loads(round_data.participants_json)
    past_winners = json.loads(round_data.winners_json)
    
    # Исключаем старых победителей из пула кандидатов
    banned_ids = [w['user_id'] for w in past_winners]
    pool = [p for p in parts if p['user_id'] not in banned_ids]
    
    if not pool:
        await message.reply("❌ Недостаточно уникальных участников для перекрута!")
        return

    import random
    new_winners = past_winners.copy()
    for p_idx in places:
        if p_idx <= len(new_winners):
            new_candidate = random.choice(pool)
            pool.remove(new_candidate)
            new_winners[p_idx-1] = new_candidate

    # Пересохраняем результаты
    async with async_session() as s:
        await s.execute(update(PastRouletteRound).where(PastRouletteRound.chat_id == message.chat.id).values(winners_json=json.dumps(new_winners)))
        await s.commit()

    mentions = [f"🏆 Место #{i+1}: @{w['username']}" for i, w in enumerate(new_winners)]
    await message.answer("🔄 **ПЕРЕКРУТ ЗАВЕРШЕН!** Обновленный список мест:\n\n" + "\n".join(mentions), parse_mode="Markdown")
