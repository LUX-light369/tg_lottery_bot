import asyncio
import json
import logging
import re
import secrets
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Tuple
from html import escape as escape_html

import pytz
from aiogram import Router, F, types, Bot, Dispatcher
from aiogram.filters import Command, StateFilter, CommandObject
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.utils.keyboard import InlineKeyboardBuilder, ReplyKeyboardBuilder
from aiogram.types import ChatPermissions, BufferedInputFile, InputMediaPhoto, ReplyKeyboardMarkup
from aiogram.exceptions import TelegramBadRequest

from database import (
    get_setting, set_setting, get_channels, add_channel, remove_channel,
    add_banned_user, is_user_banned, clean_expired_bans,
    save_roulette, update_roulette, get_roulette, get_roulette_by_id,
    get_last_finished_roulette, get_roulette_by_token, delete_old_roulettes, get_conn, init_db,
    parse_datetime
)
from random_utils import (
    generate_seed_hash, select_winners,
    create_result_image, create_random_image,
    get_verification_instruction
)

NOVOSIBIRSK = pytz.timezone('Asia/Novosibirsk')
message_queue = asyncio.Queue()
logger = logging.getLogger(__name__)

MAIN_ADMIN_ID = None
BOT_USERNAME = None
scheduled_tasks: Dict[int, asyncio.Task] = {}

def set_bot_username(username: str):
    global BOT_USERNAME
    BOT_USERNAME = username

# ---------- Очередь сообщений ----------
async def queue_worker(bot: Bot):
    while True:
        chat_id, method, kwargs = await message_queue.get()
        try:
            if method == 'send_message':
                await bot.send_message(chat_id, **kwargs)
            elif method == 'send_photo':
                await bot.send_photo(chat_id, **kwargs)
            elif method == 'send_media_group':
                await bot.send_media_group(chat_id, **kwargs)
        except Exception as e:
            logger.error(f"Queue error: {e}")
        await asyncio.sleep(2)
        message_queue.task_done()

def enqueue(chat_id: int, method: str, **kwargs):
    message_queue.put_nowait((chat_id, method, kwargs))

# ---------- Вспомогательные ----------
async def is_admin(bot: Bot, chat_id: int, user_id: int) -> bool:
    if user_id == MAIN_ADMIN_ID:
        return True
    try:
        member = await bot.get_chat_member(chat_id, user_id)
        if member.status not in ['creator', 'administrator']:
            return False
        main_member = await bot.get_chat_member(chat_id, MAIN_ADMIN_ID)
        return main_member.status in ['creator', 'administrator']
    except:
        return False

async def check_subscriptions(bot: Bot, user_id: int) -> bool:
    for ch in get_channels():
        try:
            member = await bot.get_chat_member(ch, user_id)
            if member.status in ['left', 'kicked']:
                return False
        except:
            return False
    return True

def parse_username(user: types.User) -> Optional[str]:
    return user.username

async def mute_user(bot: Bot, chat_id: int, user_id: int, minutes: int = 60):
    until = datetime.now() + timedelta(minutes=minutes)
    try:
        await bot.restrict_chat_member(chat_id, user_id,
                                       permissions=ChatPermissions(can_send_messages=False),
                                       until_date=until)
    except Exception as e:
        logger.error(f"Mute error: {e}")

async def unmute_user(bot: Bot, chat_id: int, user_id: int):
    try:
        await bot.restrict_chat_member(chat_id, user_id,
                                       permissions=ChatPermissions(
                                           can_send_messages=True,
                                           can_send_media_messages=True,
                                           can_send_other_messages=True,
                                           can_add_web_page_previews=True))
    except:
        pass

def substitute(template: str, **kwargs) -> str:
    for k, v in kwargs.items():
        template = template.replace(f"${{{k}}}", str(v))
    return template

async def send_template(bot: Bot, chat_id: int, template_str: str, **substitutions) -> types.Message:
    try:
        data = json.loads(template_str)
        if isinstance(data, dict):
            if data.get('type') == 'forward':
                return await bot.copy_message(chat_id=chat_id,
                                              from_chat_id=data['chat_id'],
                                              message_id=data['message_id'])
            elif data.get('type') == 'media':
                media_type = data['media_type']
                file_id = data['file_id']
                caption = substitute(data.get('caption', ''), **substitutions)
                if len(caption) > 1024:
                    caption = caption[:1020] + "..."
                if media_type == 'photo':
                    return await bot.send_photo(chat_id, photo=file_id, caption=caption, parse_mode='HTML')
                elif media_type == 'video':
                    return await bot.send_video(chat_id, video=file_id, caption=caption, parse_mode='HTML')
                elif media_type == 'animation':
                    return await bot.send_animation(chat_id, animation=file_id, caption=caption, parse_mode='HTML')
                elif media_type == 'document':
                    return await bot.send_document(chat_id, document=file_id, caption=caption, parse_mode='HTML')
                else:
                    return await bot.send_message(chat_id, caption)
            elif data.get('type') == 'text':
                text = substitute(data['text'], **substitutions)
                return await bot.send_message(chat_id, text, parse_mode='HTML')
    except:
        pass
    text = substitute(template_str, **substitutions)
    return await bot.send_message(chat_id, text, parse_mode='HTML')

def save_media_template(message: types.Message) -> str:
    if message.forward_from_chat and message.forward_from_message_id:
        return json.dumps({'type': 'forward', 'chat_id': message.forward_from_chat.id,
                           'message_id': message.forward_from_message_id})
    if message.photo:
        file_id = message.photo[-1].file_id
        return json.dumps({'type': 'media', 'media_type': 'photo', 'file_id': file_id,
                           'caption': message.caption or ''})
    if message.video:
        return json.dumps({'type': 'media', 'media_type': 'video', 'file_id': message.video.file_id,
                           'caption': message.caption or ''})
    if message.animation:
        return json.dumps({'type': 'media', 'media_type': 'animation', 'file_id': message.animation.file_id,
                           'caption': message.caption or ''})
    if message.document:
        return json.dumps({'type': 'media', 'media_type': 'document', 'file_id': message.document.file_id,
                           'caption': message.caption or ''})
    if message.text:
        return message.html_text
    return message.text or ''

def format_setting(value: str) -> str:
    try:
        data = json.loads(value)
        if isinstance(data, dict):
            if data.get('type') == 'text':
                return escape_html(data.get('text', '')[:50]) + ('...' if len(data.get('text',''))>50 else '')
            elif data.get('type') == 'media':
                return f"[{data.get('media_type','медиа')}]"
            elif data.get('type') == 'forward':
                return "[пересланное]"
    except:
        pass
    return escape_html(value[:50].replace('\n', ' '))

def generate_token() -> str:
    return secrets.token_hex(8)

# ---------- Сессия записи ----------
class RouletteSession:
    def __init__(self, chat_id: int, roulette_id: int, trigger: str):
        self.chat_id = chat_id
        self.roulette_id = roulette_id
        self.trigger = trigger.lower().strip()
        self.participants: Dict[int, dict] = {}
        self.muted_users: set = set()

    def process_message(self, user_id: int, username: Optional[str], message_id: int, text: str) -> Tuple[str, Optional[int], bool]:
        if is_user_banned(user_id, username):
            return 'banned', None, False
        cleaned = text.strip().lower()
        is_trigger = (cleaned == self.trigger)
        rec = self.participants.get(user_id)
        if not rec:
            rec = {'username': username, 'valid': False, 'disqualified': False,
                   'non_trigger_count': 0, 'has_trigger': False, 'trigger_msg_id': None}
            self.participants[user_id] = rec
        if rec['disqualified']:
            return 'disqualified', rec.get('trigger_msg_id'), False
        if is_trigger:
            if rec['has_trigger']:
                rec['disqualified'] = True
                return 'disqualified', rec.get('trigger_msg_id'), False
            rec['has_trigger'] = True
            rec['trigger_msg_id'] = message_id
            if username:
                rec['valid'] = True
                rec['username'] = username
                return 'valid', None, True
            else:
                return 'no_username', None, False
        else:
            rec['non_trigger_count'] += 1
            if rec['non_trigger_count'] >= 2:
                rec['disqualified'] = True
                return 'disqualified', rec.get('trigger_msg_id'), False
            return 'extra_ignored', None, False

    async def finalize(self, bot: Bot) -> List[int]:
        candidates = {uid: rec for uid, rec in self.participants.items() if rec.get('has_trigger')}
        sorted_uids = sorted(candidates.keys(), key=lambda uid: candidates[uid]['trigger_msg_id'])
        final = []
        for uid in sorted_uids:
            rec = candidates[uid]
            if rec['disqualified']:
                continue
            username = None
            try:
                member = await bot.get_chat_member(self.chat_id, uid)
                username = member.user.username
            except:
                pass
            if not username or not await check_subscriptions(bot, uid) or is_user_banned(uid, username):
                if rec.get('trigger_msg_id'):
                    try:
                        await bot.delete_message(self.chat_id, rec['trigger_msg_id'])
                    except:
                        pass
                if uid in self.participants:
                    del self.participants[uid]
                continue
            final.append(uid)
        return final

active_sessions: Dict[int, RouletteSession] = {}

# ---------- Роутеры ----------
admin_router = Router()
filter_router = Router()

# ---------- Reply‑клавиатура для обычных пользователей ----------
def user_reply_kb():
    kb = ReplyKeyboardBuilder()
    kb.button(text="🔍 Ручная проверка")
    return kb.as_markup(resize_keyboard=True)

# ---------- /start ----------
@admin_router.message(Command('start'))
async def start_cmd(message: types.Message, bot: Bot, command: CommandObject = None):
    if message.chat.type != 'private':
        return
    if message.from_user.id == MAIN_ADMIN_ID:
        await menu(message)
        return
    if command and command.args:
        token = command.args.strip()
        if token:
            await handle_verify_token(message, bot, token)
            return
    await message.answer(
        "ℹ️ Я бот для проведения честных рулеток в чате ДРУЗЬЯ ТРЕНЕРА😎. Для ручной проверки результата нажмите кнопку внизу или используйте прямую ссылку на розыгрыш!",
        reply_markup=user_reply_kb()
    )

# ---------- Обработка reply‑кнопки ----------
@admin_router.message(lambda msg: msg.chat.type == 'private' and msg.text == "🔍 Ручная проверка")
async def manual_verify_start(message: types.Message, state: FSMContext):
    if message.from_user.id == MAIN_ADMIN_ID:
        await message.answer("Админам не нужна проверка 😉")
        return
    await message.answer("Введите seed:", reply_markup=types.ReplyKeyboardRemove())
    await state.set_state(VerifyForm.waiting_for_seed)

# ---------- Альтернативная проверка (FSM) ----------
class VerifyForm(StatesGroup):
    waiting_for_seed = State()
    waiting_for_hash = State()
    waiting_for_participants = State()

@admin_router.message(StateFilter(VerifyForm.waiting_for_seed))
async def process_seed(message: types.Message, state: FSMContext):
    await state.update_data(seed=message.text.strip())
    await message.answer("Введите хеш (SHA256):")
    await state.set_state(VerifyForm.waiting_for_hash)

@admin_router.message(StateFilter(VerifyForm.waiting_for_hash))
async def process_hash(message: types.Message, state: FSMContext):
    await state.update_data(hash=message.text.strip())
    await message.answer(
        "Введите список участников (каждый с новой строки, в порядке записи,без лишних строк,только номера и юзеры).\n"
        "Если это просто рандом, введите диапазон чисел, например: 1-90"
    )
    await state.set_state(VerifyForm.waiting_for_participants)

@admin_router.message(StateFilter(VerifyForm.waiting_for_participants))
async def process_participants(message: types.Message, state: FSMContext):
    data = await state.get_data()
    seed = data['seed']
    expected_hash = data['hash']
    text = message.text.strip()
    participants = []
    if re.match(r'^\d+-\d+$', text):
        lo, hi = map(int, text.split('-'))
        participants = list(range(lo, hi+1))
    else:
        participants = [p.strip() for p in text.split('\n') if p.strip()]

    import hashlib
    computed_hash = hashlib.sha256(seed.encode()).hexdigest()
    if computed_hash != expected_hash:
        await message.answer("❌ Хеш не совпадает! Результаты могли быть подделаны или вы ошиблись при вводе данных рулетки.", reply_markup=user_reply_kb())
        await state.clear()
        return
    await state.update_data(participants=participants, seed=seed)
    await message.answer("Введите количество победителей:")
    await state.set_state('waiting_winners_count')

@admin_router.message(StateFilter('waiting_winners_count'))
async def process_winners_count(message: types.Message, state: FSMContext):
    try:
        count = int(message.text.strip())
    except:
        await message.answer("Введите число.")
        return
    data = await state.get_data()
    participants = data['participants']
    if count > len(participants):
        await message.answer("Победителей больше, чем участников.")
        return
    rng = __import__('random').Random(data['seed'])
    indices = list(range(len(participants)))
    rng.shuffle(indices)
    winners = [participants[i] for i in indices[:count]]
    report = f"🔒 Seed: <code>{escape_html(data['seed'])}</code>\n✅ Хеш совпадает!\n\n<b>Победители:</b>\n" + "\n".join(f"🏆 {escape_html(str(w))}" for w in winners)
    await message.answer(report, parse_mode='HTML', reply_markup=user_reply_kb())
    await state.clear()

# ---------- @рулетка ----------
@admin_router.message(F.text.regexp(r'@рулетка\s+(.+)'))
async def roulette_cmd(message: types.Message, bot: Bot):
    logger.info(f"Получена команда @рулетка от {message.from_user.id} в чате {message.chat.id}")
    if not await is_admin(bot, message.chat.id, message.from_user.id):
        return
    chat_id = message.chat.id
    allowed = get_setting('chat_id')
    if allowed and chat_id != int(allowed):
        return
    args = message.text.split('@рулетка', 1)[1].strip()
    winners = None
    time_str = None
    for p in args.split():
        if p.endswith('п') and p[:-1].isdigit():
            winners = int(p[:-1])
        elif re.match(r'^\d{1,2}:\d{2}$', p):
            time_str = p
    duration = int(get_setting('duration') or 5)
    trigger = get_setting('trigger') or '+'
    prizes_raw = get_setting('prizes') or ''
    prizes_list = [p.strip() for p in prizes_raw.split('\n') if p.strip()] if prizes_raw else []

    # Проверка достаточности призов
    if winners and prizes_list and len(prizes_list) < winners:
        await message.reply(f"❌ Недостаточно призов! Указано {len(prizes_list)} призов, а победителей {winners}.")
        return

    now = datetime.now(NOVOSIBIRSK)
    if time_str:
        h, m = map(int, time_str.split(':'))
        start_time = now.replace(hour=h, minute=m, second=0, microsecond=0)
        if start_time <= now:
            start_time += timedelta(days=1)
    else:
        start_time = now + timedelta(seconds=5)
    stop_time = start_time + timedelta(minutes=duration)
    seed, seed_hash = generate_seed_hash()
    verify_token = generate_token()
    rid = save_roulette(chat_id, 'waiting_start', duration, winners or 0,
                        trigger, prizes_raw, get_setting('rules'),
                        get_setting('start_msg'), get_setting('stop_msg'),
                        get_setting('result_msg'), start_time, stop_time,
                        seed=seed, seed_hash=seed_hash, verify_token=verify_token)

    # Анонс через шаблон
    announce_template = get_setting('announce_msg')
    if not announce_template:
        announce_template = (
            "📢 <b>Рулетка</b>\n"
            "Победителей: ${winners}\n"
            "Длительность: ${duration} мин.\n"
            "Старт: ${start_time} (НСК)\n"
            "🔒 Хеш честности: <code>${seed_hash}</code>"
            "${prizes}"
        )
    display_prizes = prizes_list[:winners] if winners and prizes_list else prizes_list
    prizes_str = "\n<b>Призы:</b>\n" + "\n".join(f"• {p}" for p in display_prizes) if display_prizes else ""
    await send_template(bot, chat_id, announce_template,
                        winners=str(winners) if winners else "вручную админ",
                        duration=str(duration),
                        start_time=start_time.strftime('%d.%m.%Y %H:%M'),
                        seed_hash=seed_hash,
                        prizes=prizes_str)

    if start_time > now:
        task = asyncio.create_task(schedule_start(bot, chat_id, rid, (start_time - now).total_seconds()))
        scheduled_tasks[rid] = task
    else:
        await start_recording(bot, chat_id, rid)

# ---------- Удаление триггеров до старта ----------
@filter_router.message(lambda msg: not (msg.chat.id in active_sessions) and get_roulette(msg.chat.id, 'waiting_start'))
async def pre_start_filter(message: types.Message, bot: Bot):
    if message.chat.type == 'private':
        return
    chat_id = message.chat.id
    if await is_admin(bot, chat_id, message.from_user.id):
        return
    roulette = get_roulette(chat_id, 'waiting_start')
    if not roulette:
        return
    trigger = roulette['trigger']
    text = message.text or message.caption or ''
    if text.strip().lower() == trigger.lower():
        await message.delete()
        if not hasattr(pre_start_filter, 'warned'):
            pre_start_filter.warned = {}
        prev_msg_id = pre_start_filter.warned.get(message.from_user.id)
        if prev_msg_id:
            try:
                await bot.delete_message(chat_id, prev_msg_id)
            except:
                pass
        sent = await bot.send_message(chat_id, f"<b>⏳ {message.from_user.full_name}, запись ещё не началась. Ожидайте старта!</b>")
        pre_start_filter.warned[message.from_user.id] = sent.message_id
        await asyncio.sleep(2)

# ---------- @отмена ----------
@admin_router.message(F.text.regexp(r'@отмена'))
async def cancel_cmd(message: types.Message, bot: Bot):
    if not await is_admin(bot, message.chat.id, message.from_user.id):
        return
    chat_id = message.chat.id
    session = active_sessions.pop(chat_id, None)
    if session:
        update_roulette(session.roulette_id, status='cancelled')
        enqueue(chat_id, 'send_message', text="❌ Рулетка отменена.")
        return

    roulette = get_roulette(chat_id, 'waiting_start')
    if roulette:
        rid = roulette['id']
        task = scheduled_tasks.pop(rid, None)
        if task and not task.done():
            task.cancel()
        update_roulette(rid, status='cancelled')
        enqueue(chat_id, 'send_message', text="❌ Запланированная рулетка отменена.")
    else:
        enqueue(chat_id, 'send_message', text="Нет активных рулеток для отмены.")

# ---------- @рандом ----------
@admin_router.message(F.text.regexp(r'@рандом\s+(.+)'))
async def random_cmd(message: types.Message, bot: Bot):
    if not await is_admin(bot, message.chat.id, message.from_user.id):
        return
    chat_id = message.chat.id
    args = message.text.split('@рандом', 1)[1].strip()
    winners_count = None
    range_str = None
    for p in args.split():
        if p.endswith('п') and p[:-1].isdigit():
            winners_count = int(p[:-1])
        elif re.match(r'^\d+-\d+$', p):
            range_str = p
    if not winners_count or not range_str:
        await message.reply("Формат: @рандом 2п 1-90")
        return
    try:
        lo, hi = map(int, range_str.split('-'))
    except:
        await message.reply("Неверный диапазон.")
        return
    if winners_count > (hi - lo + 1):
        await message.reply("Победителей больше, чем чисел в диапазоне.")
        return
    seed, seed_hash = generate_seed_hash()
    verify_token = generate_token()
    numbers = list(range(lo, hi+1))
    winners = select_winners(numbers, winners_count, seed)
    img_bytes = create_random_image(winners, lo, hi, datetime.now(NOVOSIBIRSK), seed_hash)
    img_file = BufferedInputFile(img_bytes.read(), filename="random.png")
    await bot.send_photo(chat_id, photo=img_file)
    verify_link = f"https://t.me/{BOT_USERNAME}?start={verify_token}"
    enqueue(chat_id, 'send_message', text=f"🔐 <b>Хеш(SHA256): <code>{seed_hash}</code>\n🔑 Seed рандома: <code>{seed}</code>\n🔍 Проверка честности: {verify_link}</b>", parse_mode='HTML', disable_web_page_preview=True)
    rid = save_roulette(chat_id, 'finished', 0, winners_count,
                        '', '', '', '', '', '', datetime.now(NOVOSIBIRSK), datetime.now(NOVOSIBIRSK),
                        seed=seed, seed_hash=seed_hash, verify_token=verify_token)
    update_roulette(rid, participants_json=json.dumps(numbers),
                    winners_json=json.dumps([numbers.index(w) for w in winners]))

# ---------- @перекрут ----------
@admin_router.message(F.text.regexp(r'@перекрут\s+(.+)'))
async def reroll_cmd(message: types.Message, bot: Bot):
    if not await is_admin(bot, message.chat.id, message.from_user.id):
        return
    chat_id = message.chat.id
    last = get_last_finished_roulette(chat_id)
    if not last:
        await message.reply("Нет завершённых рулеток за 48 ч.")
        return
    args = message.text.split('@перекрут', 1)[1].strip()
    nums = [int(s[:-1]) for s in args.replace(' ', '').split(',') if s.endswith('п')]
    if not nums:
        await message.reply("Укажите номера, напр. @перекрут 1п,3п")
        return
    participants = json.loads(last['participants_json'])
    winners_idx = json.loads(last['winners_json'])
    winners_set = set(winners_idx)
    reroll = [n for n in nums if 1 <= n <= len(winners_idx)]
    if not reroll:
        return await message.reply("Некорректные номера.")
    non_winners = [i for i in range(len(participants)) if i not in winners_set]
    if len(non_winners) < len(reroll):
        return await message.reply("Недостаточно невыигравших.")
    seed, seed_hash = generate_seed_hash()
    verify_token = generate_token()
    new_idx = select_winners(non_winners, len(reroll), seed)
    final_winners = winners_idx.copy()
    old_names = []
    for n, ni in zip(reroll, new_idx):
        old_idx = final_winners[n-1]
        final_winners[n-1] = ni
        try:
            m = await bot.get_chat_member(chat_id, participants[old_idx])
            old_names.append(f"@{m.user.username}" if m.user.username else m.user.full_name)
        except:
            old_names.append(str(participants[old_idx]))
    names = []
    for uid in participants:
        try:
            m = await bot.get_chat_member(chat_id, uid)
            names.append(f"@{m.user.username}" if m.user.username else m.user.full_name)
        except:
            names.append(str(uid))
    winner_numbers_old = [i+1 for i in winners_idx]
    winner_numbers_new = [i+1 for i in final_winners]

    # Генерируем две картинки в едином стиле (без зачёркиваний)
    img_bytes_old = create_result_image(winner_numbers_old, len(participants),
                                        parse_datetime(last['stop_time']), last['seed_hash'])
    img_bytes_new = create_result_image(winner_numbers_new, len(participants),
                                        datetime.now(NOVOSIBIRSK), seed_hash)
    img_file_old = BufferedInputFile(img_bytes_old.read(), filename="old.png")
    img_file_new = BufferedInputFile(img_bytes_new.read(), filename="new.png")

    prizes_raw = last['prizes'] or ''
    prizes_list = [p.strip() for p in prizes_raw.split('\n') if p.strip()] if prizes_raw else []
    new_winners_lines = []
    for i, idx in enumerate(final_winners):
        name = names[idx] if idx < len(names) else str(participants[idx])
        prize = prizes_list[i] if i < len(prizes_list) else "не указан"
        uid_str = participants[idx]
        new_winners_lines.append(f"🏅 {name} ({prize})\n#id{uid_str}\n")
    caption_text = "\n".join(new_winners_lines)
    if old_names:
        crossed = ", ".join(f"<s>{n}</s>" for n in old_names)
        caption_text += f"\nЛишились призов: {crossed}\n "

    result_template = last['result_msg']
    try:
        tmpl_data = json.loads(result_template)
        if isinstance(tmpl_data, dict) and tmpl_data.get('type') == 'text':
            base_text = tmpl_data['text']
            full_caption = base_text.replace('{winners}', caption_text)
        else:
            full_caption = caption_text
    except:
        full_caption = result_template.replace('{winners}', caption_text)
    if len(full_caption) > 1024:
        full_caption = full_caption[:1020] + "..."

    # Отправляем две картинки (первая с подписью)
    media = [
        InputMediaPhoto(media=img_file_old, caption=full_caption, parse_mode='HTML'),
        InputMediaPhoto(media=img_file_new)
    ]
    await bot.send_media_group(chat_id, media=media)

    verify_link = f"https://t.me/{BOT_USERNAME}?start={verify_token}"
    enqueue(chat_id, 'send_message', text=f"🔐 <b>Хеш(SHA256): <code>{seed_hash}</code>\n🔑 Seed рандома: <code>{seed}</code>\n🔍 Проверка честности: {verify_link}</b>", parse_mode='HTML', disable_web_page_preview=True)
    new_id = save_roulette(chat_id, 'finished', last['duration'], len(final_winners),
                           last['trigger'], prizes_raw, last['rules'], last['start_msg'],
                           last['stop_msg'], last['result_msg'], datetime.now(NOVOSIBIRSK),
                           datetime.now(NOVOSIBIRSK), seed=seed, seed_hash=seed_hash, verify_token=verify_token)
    update_roulette(new_id, participants_json=json.dumps(participants),
                    winners_json=json.dumps(final_winners), re_rolled_from=last['id'])

# ---------- Логика старта и записи ----------
async def schedule_start(bot, chat_id, rid, delay):
    await asyncio.sleep(delay)
    await start_recording(bot, chat_id, rid)

async def start_recording(bot: Bot, chat_id: int, rid: int):
    roulette = get_roulette_by_id(rid)
    if not roulette or roulette['status'] != 'waiting_start':
        return
    scheduled_tasks.pop(rid, None)

    rules = roulette['rules']
    if rules:
        await send_template(bot, chat_id, rules, trigger=roulette['trigger'],
                            duration=str(roulette['duration']), seed_hash=roulette.get('seed_hash',''))
        await asyncio.sleep(2)
    start = roulette['start_msg']
    if start:
        await send_template(bot, chat_id, start, trigger=roulette['trigger'])
        await asyncio.sleep(2)
    session = RouletteSession(chat_id, rid, roulette['trigger'])
    active_sessions[chat_id] = session
    update_roulette(rid, status='recording')
    stop_time_str = roulette['stop_time']
    stop_time = parse_datetime(stop_time_str) if isinstance(stop_time_str, str) else stop_time_str
    delay = (stop_time - datetime.now(NOVOSIBIRSK)).total_seconds()
    if delay > 0:
        await asyncio.sleep(delay)
    stop = roulette['stop_msg']
    if stop:
        await send_template(bot, chat_id, stop)
        await asyncio.sleep(2)
    valid_users = await session.finalize(bot)
    names_clean = []
    names_with_at = []
    for uid in valid_users:
        try:
            m = await bot.get_chat_member(chat_id, uid)
            uname = m.user.username
            if uname:
                names_clean.append(uname)
                names_with_at.append(f"@{uname}")
            else:
                full = m.user.full_name
                names_clean.append(full)
                names_with_at.append(full)
        except:
            names_clean.append(str(uid))
            names_with_at.append(str(uid))
    participants_str_clean = "\n".join(f"{i+1}. {n}" for i, n in enumerate(names_clean))
    enqueue(chat_id, 'send_message', text=f"<b>📝 Список участников ({len(valid_users)}):</b>\n<code>{participants_str_clean}</code>")
    participants_str_with_at = "\n".join(f"{i+1}. {n}" for i, n in enumerate(names_with_at))
    try:
        await bot.send_message(MAIN_ADMIN_ID, f"<b>Список участников {chat_id}:</b>\n{participants_str_with_at}")
    except:
        pass

    if roulette['winners_count'] > 0:
        # Задержка перед результатом
        await asyncio.sleep(2)
        seed = roulette['seed']
        winners = select_winners(valid_users, roulette['winners_count'], seed)
        winner_numbers = [valid_users.index(u)+1 for u in winners]
        wnames_with_at = [names_with_at[valid_users.index(u)] for u in winners]
        img_bytes = create_result_image(winner_numbers, len(valid_users), datetime.now(NOVOSIBIRSK), roulette['seed_hash'])
        img_file = BufferedInputFile(img_bytes.read(), filename="result.png")
        prizes_raw = roulette['prizes'] or ''
        prizes_list = [p.strip() for p in prizes_raw.split('\n') if p.strip()] if prizes_raw else []
        winners_lines = []
        for i, uid in enumerate(winners):
            name = wnames_with_at[i]
            prize = prizes_list[i] if i < len(prizes_list) else "не указан"
            winners_lines.append(f"🏅 {name} ({prize})\n#id{uid}\n")
        wstr = "\n".join(winners_lines)
        result_template = roulette['result_msg']
        try:
            tmpl_data = json.loads(result_template)
            if isinstance(tmpl_data, dict) and tmpl_data.get('type') == 'text':
                base_text = tmpl_data['text']
                full_caption = base_text.replace('{winners}', wstr)
            else:
                full_caption = result_template.replace('{winners}', wstr)
        except:
            full_caption = result_template.replace('{winners}', wstr)
        if len(full_caption) > 1024:
            full_caption = full_caption[:1020] + "..."
        await bot.send_photo(chat_id, photo=img_file, caption=full_caption, parse_mode='HTML')
        verify_link = f"https://t.me/{BOT_USERNAME}?start={roulette['verify_token']}"
        enqueue(chat_id, 'send_message', text=f"🔐 <b>Хеш(SHA256): <code>{roulette['seed_hash']}</code>\n🔑 Seed рандома: <code>{seed}</code>\n🔍 Проверка честности: {verify_link}</b>", parse_mode='HTML', disable_web_page_preview=True)
        update_roulette(rid, status='finished', participants_json=json.dumps(valid_users),
                        winners_json=json.dumps([valid_users.index(u) for u in winners]))
    else:
        update_roulette(rid, status='finished', participants_json=json.dumps(valid_users))
        enqueue(chat_id, 'send_message', text="<b>Админ, запусти рандом самостоятельно!</b>")
    for uid in session.muted_users:
        await unmute_user(bot, chat_id, uid)
    active_sessions.pop(chat_id, None)

# ---------- Фильтр сообщений участников ----------
async def has_active_session(message: types.Message) -> bool:
    return message.chat.id in active_sessions

@filter_router.message(has_active_session)
async def filter_msg(message: types.Message, bot: Bot):
    if message.chat.type == 'private':
        return
    session = active_sessions.get(message.chat.id)
    if not session:
        return
    if await is_admin(bot, message.chat.id, message.from_user.id):
        return
    user_id = message.from_user.id
    username = parse_username(message.from_user)
    text = message.text or message.caption or ""
    action, trigger_to_delete, need_sub_check = session.process_message(user_id, username, message.message_id, text)

    if action == 'valid':
        if not await check_subscriptions(bot, user_id):
            await message.reply("<b>⚠️ Подпишись на канал до конца записи, иначе не попадешь в список!</b>")
        return
    elif action == 'no_username':
        await message.reply("<b>⚠️ Установи юзернейм в настройках Telegram до конца записи, иначе не попадешь в список!</b>")
    elif action == 'disqualified':
        await message.delete()
        if trigger_to_delete:
            try:
                await bot.delete_message(message.chat.id, trigger_to_delete)
            except:
                pass
        await mute_user(bot, message.chat.id, user_id)
        session.muted_users.add(user_id)
        mention = f"@{username}" if username else message.from_user.full_name
        enqueue(message.chat.id, 'send_message', text=f"⛔ <b>{mention} исключается из рулетки за нарушение правил!</b>")
    elif action == 'extra_ignored':
        await message.delete()
    elif action == 'ignored':
        await message.delete()
    elif action == 'banned':
        await message.delete()
        await mute_user(bot, message.chat.id, user_id)
        session.muted_users.add(user_id)
        mention = f"@{username}" if username else message.from_user.full_name
        enqueue(message.chat.id, 'send_message', text=f"🚫 <b>{mention}, тебе нельзя участвовать в данной рулетке!</b>")

# ---------- Меню настроек ----------
class SettingsForm(StatesGroup):
    waiting_for_chat_id = State()
    waiting_for_duration = State()
    waiting_for_trigger = State()
    waiting_for_prizes = State()
    waiting_for_rules = State()
    waiting_for_start_msg = State()
    waiting_for_stop_msg = State()
    waiting_for_result_msg = State()
    waiting_for_announce_msg = State()
    waiting_for_channel_add = State()
    waiting_for_channel_del = State()
    waiting_for_ban = State()
    waiting_for_max = State()

def build_menu_kb():
    kb = InlineKeyboardBuilder()
    kb.button(text="📌 Текущие настройки", callback_data="view")
    kb.button(text="💬 Чат проведения", callback_data="set_chat")
    kb.button(text="⏱ Время записи", callback_data="set_duration")
    kb.button(text="🔡 Триггер", callback_data="set_trigger")
    kb.button(text="🏆 Призы", callback_data="set_prizes")
    kb.button(text="📜 Правила", callback_data="set_rules")
    kb.button(text="🚀 Старт", callback_data="set_start_msg")
    kb.button(text="⏹ Стоп", callback_data="set_stop_msg")
    kb.button(text="📝 Пост победителей", callback_data="set_result_msg")
    kb.button(text="📢 Анонс", callback_data="set_announce_msg")
    kb.button(text="💬 Каналы подписки", callback_data="channels_menu")
    kb.button(text="🚫 Запреты", callback_data="ban_menu")
    kb.button(text="👥 Макс. участников", callback_data="set_max")
    kb.adjust(2)
    return kb.as_markup()

@admin_router.message(Command('menu'))
async def menu(message: types.Message):
    if message.from_user.id != MAIN_ADMIN_ID:
        return
    await message.answer("Настройки:", reply_markup=build_menu_kb())

def back_btn():
    kb = InlineKeyboardBuilder()
    kb.button(text="« Назад", callback_data="back_to_menu")
    return kb.as_markup()

@admin_router.callback_query(F.data == "back_to_menu")
async def back_menu(call: types.CallbackQuery, state: FSMContext):
    await state.clear()
    await call.message.edit_text("Настройки:", reply_markup=build_menu_kb())

@admin_router.callback_query(F.data == "view")
async def view_settings(call: types.CallbackQuery):
    prizes_raw = get_setting('prizes') or ''
    prizes_display = escape_html(prizes_raw.replace('\n', ', ')) if prizes_raw else 'нет'
    s = f"""<b>Текущие настройки:</b>
Триггер: {escape_html(get_setting('trigger'))}
Длительность: {escape_html(get_setting('duration'))} мин
Макс. участников: {escape_html(get_setting('max_participants')) or 'нет'}
Чат: {escape_html(get_setting('chat_id')) or 'не задан'}
Каналы: {escape_html(', '.join(get_channels())) if get_channels() else 'нет'}
Призы: {prizes_display}
Правила: {format_setting(get_setting('rules'))}
Старт: {format_setting(get_setting('start_msg'))}
Стоп: {format_setting(get_setting('stop_msg'))}
Результат: {format_setting(get_setting('result_msg'))}
Анонс: {format_setting(get_setting('announce_msg'))}"""
    await call.message.edit_text(s, reply_markup=back_btn(), parse_mode='HTML')
    await call.answer()

# ---------- Обработчики настроек ----------
@admin_router.callback_query(F.data == "set_chat")
async def set_chat_start(call: types.CallbackQuery, state: FSMContext):
    await call.message.edit_text("Введите ID чата (текущий: " +
                                 escape_html(get_setting('chat_id') or 'не задан') + ")", reply_markup=back_btn())
    await state.set_state(SettingsForm.waiting_for_chat_id)
    await call.answer()

@admin_router.message(StateFilter(SettingsForm.waiting_for_chat_id))
async def set_chat_finish(message: types.Message, state: FSMContext):
    if not message.text:
        await message.answer("Введите числовой ID.", reply_markup=back_btn())
        return
    try:
        chat_id = int(message.text.strip())
        set_setting('chat_id', str(chat_id))
        await message.answer(f"Чат установлен: {chat_id}", reply_markup=back_btn())
    except ValueError:
        await message.answer("Неверный ID.", reply_markup=back_btn())
    await state.clear()

@admin_router.callback_query(F.data == "set_duration")
async def set_duration_start(call: types.CallbackQuery, state: FSMContext):
    await call.message.edit_text("Введите длительность в минутах (сейчас " +
                                 escape_html(get_setting('duration')) + "):", reply_markup=back_btn())
    await state.set_state(SettingsForm.waiting_for_duration)
    await call.answer()

@admin_router.message(StateFilter(SettingsForm.waiting_for_duration))
async def set_duration_finish(message: types.Message, state: FSMContext):
    if message.text and message.text.isdigit():
        set_setting('duration', message.text.strip())
        await message.answer(f"Длительность: {message.text} мин.", reply_markup=back_btn())
    else:
        await message.answer("Введите число.", reply_markup=back_btn())
    await state.clear()

@admin_router.callback_query(F.data == "set_trigger")
async def set_trigger_start(call: types.CallbackQuery, state: FSMContext):
    await call.message.edit_text("Отправьте новый триггер (сейчас «" +
                                 escape_html(get_setting('trigger')) + "»):", reply_markup=back_btn())
    await state.set_state(SettingsForm.waiting_for_trigger)
    await call.answer()

@admin_router.message(StateFilter(SettingsForm.waiting_for_trigger))
async def set_trigger_finish(message: types.Message, state: FSMContext):
    new_trigger = message.text.strip() if message.text else ""
    if new_trigger:
        set_setting('trigger', new_trigger)
        await message.answer(f"Триггер: «{escape_html(new_trigger)}»", reply_markup=back_btn())
    else:
        await message.answer("Не может быть пустым.", reply_markup=back_btn())
    await state.clear()

@admin_router.callback_query(F.data == "set_prizes")
async def set_prizes_start(call: types.CallbackQuery, state: FSMContext):
    await call.message.edit_text("Введите призы, каждый с новой строки (сейчас:\n" +
                                 escape_html(get_setting('prizes') or 'нет') + ")", reply_markup=back_btn())
    await state.set_state(SettingsForm.waiting_for_prizes)
    await call.answer()

@admin_router.message(StateFilter(SettingsForm.waiting_for_prizes))
async def set_prizes_finish(message: types.Message, state: FSMContext):
    prizes_text = message.text.strip()
    set_setting('prizes', prizes_text)
    await message.answer("Призы сохранены.", reply_markup=back_btn())
    await state.clear()

@admin_router.callback_query(F.data == "set_rules")
async def set_rules_start(call: types.CallbackQuery, state: FSMContext):
    await call.message.edit_text("Отправьте текст правил (можно с ${trigger} и ${duration}) или перешлите медиа.",
                                 reply_markup=back_btn())
    await state.set_state(SettingsForm.waiting_for_rules)
    await call.answer()

@admin_router.message(StateFilter(SettingsForm.waiting_for_rules))
async def set_rules_finish(message: types.Message, state: FSMContext):
    data = save_media_template(message)
    set_setting('rules', data)
    await message.answer("Правила сохранены.", reply_markup=back_btn())
    await state.clear()

@admin_router.callback_query(F.data == "set_start_msg")
async def set_start_msg_start(call: types.CallbackQuery, state: FSMContext):
    await call.message.edit_text("Отправьте стартовое сообщение (можно с ${trigger}) или медиа.",
                                 reply_markup=back_btn())
    await state.set_state(SettingsForm.waiting_for_start_msg)
    await call.answer()

@admin_router.message(StateFilter(SettingsForm.waiting_for_start_msg))
async def set_start_msg_finish(message: types.Message, state: FSMContext):
    data = save_media_template(message)
    set_setting('start_msg', data)
    await message.answer("Стартовое сообщение сохранено.", reply_markup=back_btn())
    await state.clear()

@admin_router.callback_query(F.data == "set_stop_msg")
async def set_stop_msg_start(call: types.CallbackQuery, state: FSMContext):
    await call.message.edit_text("Отправьте стоп-сообщение или медиа.",
                                 reply_markup=back_btn())
    await state.set_state(SettingsForm.waiting_for_stop_msg)
    await call.answer()

@admin_router.message(StateFilter(SettingsForm.waiting_for_stop_msg))
async def set_stop_msg_finish(message: types.Message, state: FSMContext):
    data = save_media_template(message)
    set_setting('stop_msg', data)
    await message.answer("Стоп-сообщение сохранено.", reply_markup=back_btn())
    await state.clear()

@admin_router.callback_query(F.data == "set_result_msg")
async def set_result_msg_start(call: types.CallbackQuery, state: FSMContext):
    await call.message.edit_text("Отправьте шаблон результата (можно с {winners}) или медиа.",
                                 reply_markup=back_btn())
    await state.set_state(SettingsForm.waiting_for_result_msg)
    await call.answer()

@admin_router.message(StateFilter(SettingsForm.waiting_for_result_msg))
async def set_result_msg_finish(message: types.Message, state: FSMContext):
    data = save_media_template(message)
    set_setting('result_msg', data)
    await message.answer("Пост победителей сохранён.", reply_markup=back_btn())
    await state.clear()

@admin_router.callback_query(F.data == "set_announce_msg")
async def set_announce_msg_start(call: types.CallbackQuery, state: FSMContext):
    await call.message.edit_text(
        "Отправьте шаблон анонса (можно использовать переменные:\n"
        "${winners}, ${duration}, ${start_time}, ${seed_hash}, ${prizes})\n"
        "или перешлите медиа с подписью.",
        reply_markup=back_btn()
    )
    await state.set_state(SettingsForm.waiting_for_announce_msg)
    await call.answer()

@admin_router.message(StateFilter(SettingsForm.waiting_for_announce_msg))
async def set_announce_msg_finish(message: types.Message, state: FSMContext):
    data = save_media_template(message)
    set_setting('announce_msg', data)
    await message.answer("Анонс сохранён.", reply_markup=back_btn())
    await state.clear()

@admin_router.callback_query(F.data == "channels_menu")
async def channels_menu(call: types.CallbackQuery):
    kb = InlineKeyboardBuilder()
    kb.button(text="➕ Добавить канал", callback_data="channel_add")
    kb.button(text="➖ Удалить канал", callback_data="channel_del")
    kb.button(text="« Назад", callback_data="back_to_menu")
    channels_list = get_channels()
    channels_text = ', '.join(channels_list) if channels_list else 'нет'
    await call.message.edit_text("Каналы: " + escape_html(channels_text),
                                 reply_markup=kb.as_markup())
    await call.answer()

@admin_router.callback_query(F.data == "channel_add")
async def channel_add_start(call: types.CallbackQuery, state: FSMContext):
    await call.message.edit_text("Перешлите сообщение из канала или введите @username.",
                                 reply_markup=back_btn())
    await state.set_state(SettingsForm.waiting_for_channel_add)
    await call.answer()

@admin_router.message(StateFilter(SettingsForm.waiting_for_channel_add))
async def channel_add_finish(message: types.Message, state: FSMContext):
    if message.forward_from_chat and message.forward_from_chat.type == 'channel':
        ch_id = message.forward_from_chat.id
        add_channel(str(ch_id))
        await message.answer(f"Канал {ch_id} добавлен.", reply_markup=back_btn())
    elif message.text and message.text.startswith('@'):
        try:
            chat = await message.bot.get_chat(message.text)
            add_channel(str(chat.id))
            await message.answer(f"Канал {chat.id} добавлен.", reply_markup=back_btn())
        except:
            await message.answer("Не удалось найти канал.", reply_markup=back_btn())
    else:
        await message.answer("Неверный формат.", reply_markup=back_btn())
    await state.clear()

@admin_router.callback_query(F.data == "channel_del")
async def channel_del_start(call: types.CallbackQuery, state: FSMContext):
    await call.message.edit_text("Введите ID канала или @username для удаления.",
                                 reply_markup=back_btn())
    await state.set_state(SettingsForm.waiting_for_channel_del)
    await call.answer()

@admin_router.message(StateFilter(SettingsForm.waiting_for_channel_del))
async def channel_del_finish(message: types.Message, state: FSMContext):
    ch = message.text.strip()
    remove_channel(ch)
    await message.answer(f"Канал {ch} удалён (если был).", reply_markup=back_btn())
    await state.clear()

@admin_router.callback_query(F.data == "ban_menu")
async def ban_menu(call: types.CallbackQuery):
    kb = InlineKeyboardBuilder()
    kb.button(text="🚫 Запретить", callback_data="ban_add")
    kb.button(text="📜 Список запретов", callback_data="ban_list")
    kb.button(text="« Назад", callback_data="back_to_menu")
    await call.message.edit_text("Управление запретами.", reply_markup=kb.as_markup())
    await call.answer()

@admin_router.callback_query(F.data == "ban_add")
async def ban_add_start(call: types.CallbackQuery, state: FSMContext):
    await call.message.edit_text("Введите @username или user_id, дни, причина (опционально). Пример: @user 30 спам",
                                 reply_markup=back_btn())
    await state.set_state(SettingsForm.waiting_for_ban)
    await call.answer()

@admin_router.message(StateFilter(SettingsForm.waiting_for_ban))
async def ban_add_finish(message: types.Message, state: FSMContext):
    parts = message.text.split()
    if len(parts) < 2:
        await message.answer("Формат: @user или user_id, дни.", reply_markup=back_btn())
        return
    user_ident = parts[0]
    try:
        days = int(parts[1])
    except:
        await message.answer("Количество дней должно быть числом.", reply_markup=back_btn())
        return
    reason = " ".join(parts[2:]) if len(parts) > 2 else ""
    if user_ident.startswith('@'):
        add_banned_user(None, user_ident[1:], days, reason)
    else:
        try:
            add_banned_user(int(user_ident), None, days, reason)
        except:
            await message.answer("ID должен быть числом.", reply_markup=back_btn())
            return
    await message.answer(f"Пользователь {escape_html(user_ident)} забанен на {days} дн.", reply_markup=back_btn())
    await state.clear()

@admin_router.callback_query(F.data == "ban_list")
async def ban_list_view(call: types.CallbackQuery):
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM banned_users WHERE banned_until > ?",
                            (datetime.now(),)).fetchall()
    if rows:
        text = "Активные запреты:\n" + "\n".join(
            f"- {'@'+r['username'] if r['username'] else r['user_id']} до {r['banned_until'][:19]} ({r['reason']})"
            for r in rows
        )
    else:
        text = "Нет активных запретов."
    await call.message.edit_text(text, reply_markup=back_btn())
    await call.answer()

@admin_router.callback_query(F.data == "set_max")
async def set_max_start(call: types.CallbackQuery, state: FSMContext):
    await call.message.edit_text("Введите максимум участников (0 — без ограничения). Сейчас: " +
                                 escape_html(get_setting('max_participants') or '0'), reply_markup=back_btn())
    await state.set_state(SettingsForm.waiting_for_max)
    await call.answer()

@admin_router.message(StateFilter(SettingsForm.waiting_for_max))
async def set_max_finish(message: types.Message, state: FSMContext):
    if message.text and message.text.isdigit():
        set_setting('max_participants', message.text.strip())
        await message.answer(f"Ограничение: {message.text}.", reply_markup=back_btn())
    else:
        await message.answer("Введите число.", reply_markup=back_btn())
    await state.clear()

# ---------- Обработка проверки по токену ----------
async def handle_verify_token(message: types.Message, bot: Bot, token: str):
    roulette = get_roulette_by_token(token)
    if not roulette:
        await message.answer("❌ <b>Недействительный или устаревший токен проверки!</b>")
        return
    participants = json.loads(roulette['participants_json']) if roulette['participants_json'] else []
    winners_idx = json.loads(roulette['winners_json']) if roulette['winners_json'] else []
    names = []
    for uid in participants:
        try:
            m = await bot.get_chat_member(roulette['chat_id'], uid)
            names.append(f"@{m.user.username}" if m.user.username else m.user.full_name)
        except:
            names.append(str(uid))
    winners_names = [names[idx] for idx in winners_idx] if winners_idx else []
    seed = roulette.get('seed', 'не указан')
    seed_hash = roulette.get('seed_hash', 'не указан')
    start_time = parse_datetime(roulette['start_time']).strftime('%d.%m.%Y %H:%M') if roulette['start_time'] else '?'
    participants_code = json.dumps(participants, ensure_ascii=False)
    python_code = (
        "import random\n"
        f"seed = {repr(seed)}\n"
        f"participants = {participants_code}\n"
        f"winners_count = {len(winners_idx)}\n"
        "rng = random.Random(seed)\n"
        "indices = list(range(len(participants)))\n"
        "rng.shuffle(indices)\n"
        "winners = [participants[i] for i in indices[:winners_count]]\n"
        "print(winners)"
    )
    report = (
        "<a href="https://i.postimg.cc/yBcHJ1hR/20260901-234607.jpg">🔍</a> <b>Проверка честности розыгрыша</b>\n\n"
        f"📅 Дата: {start_time}\n"
        f"👥 Участников: {len(participants)}\n"
        f"🎲 Победители: {', '.join(winners_names) if winners_names else 'нет'}\n\n"
        f"🔑 <b>Seed (секретное число):</b> <code>{escape_html(seed)}</code>\n"
        f"🔐 <b>Хеш SHA256:</b> <code>{escape_html(seed_hash)}</code>\n\n"
        "ℹ️ <b>Как проверить:</b>\n"
        "1. Убедитесь, что хеш совпадает с объявленным до начала розыгрыша.\n"
        "2. Перейдите на сайт https://emn178.github.io/online-tools/sha256.html и введите seed — получите хеш. Сравните!\n"
        "3. Скопируйте открытый исходный код рандома(seed и список подставлены) под этой инструкцией, откройте сайт любого онлайн компилятора Python кода, например https://online-python.netlify.app/.\n
        "4. Вставьте скопированный код и нажмите в левом верхнем углу зелёную кнопку ЗАПУСК,в графе ВЫВОД появиться результат рулетки. Сравните!\n\n"
        "<b>Готовый код для проверки:</b>\n"
        f"<pre>{escape_html(python_code)}</pre>\n\n"
        "<b>✅ Если результат совпал — розыгрыш честный!</b>"
    )
    await message.answer(report, parse_mode='HTML', reply_markup=user_reply_kb() if message.from_user.id != MAIN_ADMIN_ID else None)

# ---------- Периодическая очистка ----------
async def clean_old_roulettes(bot: Bot):
    while True:
        delete_old_roulettes(48)
        clean_expired_bans()
        await asyncio.sleep(3600)

# ---------- Регистрация роутеров ----------
def setup_routers(dp: Dispatcher, bot: Bot, main_admin_id: int):
    global MAIN_ADMIN_ID
    MAIN_ADMIN_ID = main_admin_id
    dp.include_router(admin_router)
    dp.include_router(filter_router)
