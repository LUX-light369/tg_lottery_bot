import datetime
import re
import zoneinfo
import os
import json
import random
from aiogram import Bot, Router, F
from aiogram.types import Message, ChatPermissions, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.filters import Command

from database import (
    async_session, RouletteSession, RouletteParticipant, 
    PastRouletteRound, BotConfig, WinnerCooldown
)
from sqlalchemy import select, update, delete
from utils.crypto import generate_provably_fair_round, get_fair_winners
from utils.image_gen import generate_gta_results
from scheduler import scheduler
from config import DEFAULT_TZ, ADMIN_ID

router = Router()
tz_nsk = zoneinfo.ZoneInfo(DEFAULT_TZ)

def clean_compare(str1: str, str2: str) -> bool:
    if not str1 or not str2: return False
    return str1.strip().encode('utf-8') == str2.strip().encode('utf-8')

async def start_recording_now(bot: Bot, chat_id: int, duration_minutes: int = 10):
    async with async_session() as s:
        cfg = (await s.execute(select(BotConfig).where(BotConfig.id == 1))).scalar_one()
        await s.execute(update(RouletteSession).where(RouletteSession.chat_id == chat_id).values(is_joined_active=True))
        await s.commit()
    msg = cfg.r_start_msg.format(trigger=f" {cfg.r_trigger} ")
    await bot.send_message(chat_id, msg, parse_mode="HTML")

@router.message(F.chat.type.in_({"group", "supergroup"}))
@router.message(Command("отмена"))
async def cancel_roulette_cmd(message: Message, bot: Bot):
    if not (message.text and ("@отмена" in message.text or message.text.startswith("/отмена"))): return
    try:
        admins = [a.user.id for a in await bot.get_chat_administrators(message.chat.id)]
        if message.from_user.id not in admins and message.from_user.id != ADMIN_ID: return
    except: return

    async with async_session() as s:
        session_data = (await s.execute(select(RouletteSession).where(RouletteSession.chat_id == message.chat.id))).scalar_one_or_none()
        if not session_data or not session_data.is_active:
            await message.reply("❌ В данном чате нет активной рулетки.")
            return
        await s.execute(delete(RouletteSession).where(RouletteSession.chat_id == message.chat.id))
        await s.execute(delete(RouletteParticipant).where(RouletteParticipant.chat_id == message.chat.id))
        await s.commit()

    for job in scheduler.get_jobs():
        if job.args and len(job.args) > 1 and job.args[1] == message.chat.id:
            try: job.remove()
            except: pass
    await message.answer("🛑 **Запись рулетки принудительно отменена администратором!**")

@router.message(F.chat.type.in_({"group", "supergroup"}))
@router.message(Command("рулетка"))
async def process_roulette_cmd(message: Message, bot: Bot):
    if not message.text: return
    if not (message.text.startswith("/рулетка") or "@рулетка" in message.text): return
    try:
        admins = [a.user.id for a in await bot.get_chat_administrators(message.chat.id)]
        if message.from_user.id not in admins and message.from_user.id != ADMIN_ID: return
    except: return

    raw_text = message.text.replace("@рулетка", "").replace("/рулетка", "").strip()
    
    async with async_session() as s:
        cfg = (await s.execute(select(BotConfig).where(BotConfig.id == 1))).scalar_one()

    p_match = re.search(r'(\d+)\s*[пПpP]', raw_text)
    winners_count = int(p_match.group(1)) if p_match else 1
    
    m_match = re.search(r'(\d+)\s*[мМmM]', raw_text)
    # ИСПРАВЛЕНО: Если 'м' не передано в команде, берем r_default_duration из настроек базы данных
    duration_minutes = int(m_match.group(1)) if m_match else cfg.r_default_duration
    
    t_match = re.search(r'(\d{2}:\d{2})', raw_text)
    
    prizes_list = raw_text
    if p_match: prizes_list = prizes_list.replace(p_match.group(0), "")
    if m_match: prizes_list = prizes_list.replace(m_match.group(0), "")
    if t_match: prizes_list = prizes_list.replace(t_match.group(0), "")
    prizes_list = prizes_list.strip()

    async with async_session() as s:
        await s.execute(delete(RouletteSession).where(RouletteSession.chat_id == message.chat.id))
        await s.execute(delete(RouletteParticipant).where(RouletteParticipant.chat_id == message.chat.id))
        seed, salt, sha_hash = generate_provably_fair_round()
        session_data = RouletteSession(
            chat_id=message.chat.id, is_active=True,
            is_joined_active=False if t_match else True,
            winners_count=winners_count, seed=seed, salt=salt, sha_hash=sha_hash,
            prizes=prizes_list or cfg.r_default_prizes
        )
        s.add(session_data)
        await s.commit()

    if t_match:
        target_time_str = t_match.group(1)
        now = datetime.datetime.now(tz_nsk)
        target_time = datetime.datetime.strptime(target_time_str, "%H:%M").time()
        run_date = datetime.datetime.combine(now.date(), target_time).replace(tzinfo=tz_nsk)
        if run_date < now: run_date += datetime.timedelta(days=1)
            
        await message.answer(f"📢 **Рулетка запланирована!**\n🏆 Мест: `{winners_count}`\n⏱ Запись: `{duration_minutes} мин`\nСтарт автоматически в **{target_time_str}** по НСК.\n\n🔐 SHA-256:\n`{sha_hash}`", parse_mode="Markdown")
        scheduler.add_job(start_recording_now, 'date', run_date=run_date, args=[bot, message.chat.id, duration_minutes])
        scheduler.add_job(stop_roulette_action, 'date', run_date=run_date + datetime.timedelta(minutes=duration_minutes), args=[bot, message.chat.id])
    else:
        await message.answer(f"🎰 **Рулетка запущена!**\nОтправляйте триггер `{cfg.r_trigger}` для участия!\n🏆 Мест: `{winners_count}`\n⏱ Время на запись: `{duration_minutes} мин`\n🔐 SHA-256:\n`{sha_hash}`", parse_mode="Markdown")
        scheduler.add_job(stop_roulette_action, 'date', run_date=datetime.datetime.now(tz_nsk) + datetime.timedelta(minutes=duration_minutes), args=[bot, message.chat.id])

async def stop_roulette_action(bot: Bot, chat_id: int):
    async with async_session() as s:
        session_data = (await s.execute(select(RouletteSession).where(RouletteSession.chat_id == chat_id))).scalar_one_or_none()
        if not session_data or not session_data.is_active: return
        cfg = (await s.execute(select(BotConfig).where(BotConfig.id == 1))).scalar_one()
        parts = (await s.execute(select(RouletteParticipant).where(RouletteParticipant.chat_id == chat_id, RouletteParticipant.is_disqualified == False))).scalars().all()
        cooldowns = (await s.execute(select(WinnerCooldown).where(WinnerCooldown.until_date > datetime.datetime.utcnow()))).scalars().all()
        banned_names = [c.username for c in cooldowns]
        valid_parts = [p for p in parts if p.username not in banned_names]

    await bot.send_message(chat_id, cfg.r_stop_msg, parse_mode="HTML")
    if not valid_parts:
        await bot.send_message(chat_id, "🤷‍♂️ Время записи вышло. Валидных участников нет.")
        return

    winners = get_fair_winners(valid_parts, session_data.winners_count, session_data.seed, session_data.salt)
    prizes_split = [p.strip() for p in session_data.prizes.split(",") if p.strip()]
    winner_mentions = []
    for idx, w in enumerate(winners):
        prize = prizes_split[0] if len(prizes_split) == 1 else (prizes_split[idx] if idx < len(prizes_split) else "Приз")
        winner_mentions.append(f"🏆 Место #{idx+1}: @{w.username} — 🎁 **{prize}**")

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

    async with async_session() as s:
        p_json = json.dumps([{"user_id": p.user_id, "username": p.username} for p in valid_parts])
        w_json = json.dumps([{"user_id": w.user_id, "username": w.username} for w in winners])
        await s.merge(PastRouletteRound(chat_id=chat_id, winners_json=w_json, participants_json=p_json, updated_at=datetime.datetime.utcnow()))
        await s.execute(delete(RouletteParticipant).where(RouletteParticipant.chat_id == chat_id))
        await s.execute(update(RouletteSession).where(RouletteSession.chat_id == chat_id).values(is_active=False))
        await s.commit()

@router.message(F.chat.type.in_({"group", "supergroup"}))
async def collect_triggers(message: Message, bot: Bot):
    if not message.text: return
    async with async_session() as s:
        session_data = (await s.execute(select(RouletteSession).where(RouletteSession.chat_id == message.chat.id))).scalar_one_or_none()
        if not session_data or not session_data.is_active or not session_data.is_joined_active: return
        cfg = (await s.execute(select(BotConfig).where(BotConfig.id == 1))).scalar_one()

    if clean_compare(message.text, cfg.r_trigger):
        if not message.from_user.username:
            await message.reply("⚠️ Пропишите @username в профиле!")
            return
        async with async_session() as s:
            exist = (await s.execute(select(RouletteParticipant).where(RouletteParticipant.chat_id == message.chat.id, RouletteParticipant.user_id == message.from_user.id))).scalar_one_or_none()
            if exist:
                if not exist.is_disqualified:
                    await s.execute(update(RouletteParticipant).where(RouletteParticipant.id == exist.id).values(is_disqualified=True))
                    await s.commit()
                    await message.answer(f"🚫 @{message.from_user.username} дисквалифицирован за спам!")
                try: await message.delete()
                except: pass
                return
            s.add(RouletteParticipant(chat_id=message.chat.id, user_id=message.from_user.id, username=message.from_user.username))
            await s.commit()
