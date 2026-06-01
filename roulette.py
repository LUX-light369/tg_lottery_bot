import asyncio
import json
import logging
import re
from datetime import datetime, timedelta
from typing import Optional, Dict, List, Tuple

import pytz
from aiogram import Router, F, types, Bot, Dispatcher
from aiogram.filters import Command, StateFilter
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.types import ChatPermissions, BufferedInputFile, MessageEntity

from database import (
    get_setting, set_setting, get_channels, add_channel, remove_channel,
    add_banned_user, is_user_banned, clean_expired_bans,
    save_roulette, update_roulette, get_roulette, get_roulette_by_id,
    get_last_finished_roulette, delete_old_roulettes, get_conn, init_db,
    parse_datetime
)
from random_utils import (
    generate_seed_hash, select_winners,
    create_result_image, create_random_image, get_verification_instruction
)

NOVOSIBIRSK = pytz.timezone('Asia/Novosibirsk')
message_queue = asyncio.Queue()
logger = logging.getLogger(__name__)

MAIN_ADMIN_ID = None

# ---------- Очередь сообщений (задержка 2 сек) ----------
async def queue_worker(bot: Bot):
    while True:
        chat_id, method, kwargs = await message_queue.get()
        try:
            if method == 'send_message':
                await bot.send_message(chat_id, **kwargs)
            elif method == 'send_photo':
                await bot.send_photo(chat_id, **kwargs)
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
    channels = get_channels()
    if not channels:
        return True
    for ch in channels:
        try:
            member = await bot.get_chat_member(ch, user_id)
            if member.status in ['left', 'kicked']:
                logger.info(f"User {user_id} not subscribed to {ch}")
                return False
        except Exception as e:
            logger.error(f"Subscription check error for channel {ch}: {e}")
            return False
    return True

def parse_username(user: types.User) -> Optional[str]:
    return user.username

async def mute_user(bot: Bot, chat_id: int, user_id: int, minutes: int = 60):
    until = datetime.now() + timedelta(minutes=minutes)
    try:
        await bot.restrict_chat_member(
            chat_id, user_id,
            permissions=ChatPermissions(can_send_messages=False),
            until_date=until
        )
    except Exception as e:
        logger.error(f"Mute error: {e}")

async def unmute_user(bot: Bot, chat_id: int, user_id: int):
    try:
        await bot.restrict_chat_member(
            chat_id, user_id,
            permissions=ChatPermissions(
                can_send_messages=True,
                can_send_media_messages=True,
                can_send_other_messages=True,
                can_add_web_page_previews=True
            )
        )
    except:
        pass

def substitute(template: str, **kwargs) -> str:
    for k, v in kwargs.items():
        template = template.replace(f"${{{k}}}", str(v))
    return template

async def send_template(bot: Bot, chat_id: int, template_str: str, **substitutions) -> types.Message:
    """Отправляет шаблон с поддержкой текста, форматирования и медиа."""
    try:
        data = json.loads(template_str)
        if isinstance(data, dict):
            if data.get('type') == 'forward':
                return await bot.copy_message(
                    chat_id=chat_id,
                    from_chat_id=data['chat_id'],
                    message_id=data['message_id']
                )
            elif data.get('type') == 'media':
                media_type = data['media_type']
                file_id = data['file_id']
                caption = substitute(data.get('caption', ''), **substitutions)
                if media_type == 'photo':
                    return await bot.send_photo(chat_id, photo=file_id, caption=caption)
                elif media_type == 'video':
                    return await bot.send_video(chat_id, video=file_id, caption=caption)
                elif media_type == 'animation':
                    return await bot.send_animation(chat_id, animation=file_id, caption=caption)
                elif media_type == 'document':
                    return await bot.send_document(chat_id, document=file_id, caption=caption)
                else:
                    return await bot.send_message(chat_id, caption)
            elif data.get('type') == 'text':
                text = substitute(data['text'], **substitutions)
                entities = []
                if data.get('entities'):
                    for e in data['entities']:
                        entities.append(MessageEntity(**e))
                return await bot.send_message(chat_id, text, entities=entities)
    except:
        pass
    # Обычный текст
    text = substitute(template_str, **substitutions)
    return await bot.send_message(chat_id, text)

def save_media_template(message: types.Message) -> str:
    """Сохраняет шаблон с поддержкой медиа, пересылки и форматирования."""
    if message.forward_from_chat and message.forward_from_message_id:
        return json.dumps({
            'type': 'forward',
            'chat_id': message.forward_from_chat.id,
            'message_id': message.forward_from_message_id
        })
    if message.photo:
        file_id = message.photo[-1].file_id
        return json.dumps({
            'type': 'media', 'media_type': 'photo', 'file_id': file_id,
            'caption': message.caption or '', 'entities': []
        })
    if message.video:
        return json.dumps({
            'type': 'media', 'media_type': 'video', 'file_id': message.video.file_id,
            'caption': message.caption or '', 'entities': []
        })
    if message.animation:
        return json.dumps({
            'type': 'media', 'media_type': 'animation', 'file_id': message.animation.file_id,
            'caption': message.caption or '', 'entities': []
        })
    if message.document:
        return json.dumps({
            'type': 'media', 'media_type': 'document', 'file_id': message.document.file_id,
            'caption': message.caption or '', 'entities': []
        })
    # Текст с entities
    entities = []
    if message.entities:
        entities = [ent.model_dump() for ent in message.entities]
    return json.dumps({
        'type': 'text',
        'text': message.text or '',
        'entities': entities
    })

def format_setting(value: str) -> str:
    """Преобразует сохранённое значение в читаемый вид для настроек."""
    try:
        data = json.loads(value)
        if isinstance(data, dict):
            if data.get('type') == 'text':
                return data.get('text', '')[:50] + ('...' if len(data.get('text',''))>50 else '')
            elif data.get('type') == 'media':
                return f"[{data.get('media_type','медиа')}]"
            elif data.get('type') == 'forward':
                return "[пересланное сообщение]"
    except:
        pass
    return value[:50]

# ---------- Сессия записи ----------
class RouletteSession:
    def __init__(self, chat_id: int, roulette_id: int, trigger: str):
        self.chat_id = chat_id
        self.roulette_id = roulette_id
        self.trigger = trigger.lower().strip()
        self.participants: Dict[int, dict] = {}
        self.valid_order: List[int] = []

    def process_message(self, user_id: int, username: Optional[str], message_id: int, text: str) -> Tuple[str, Optional[int], bool]:
        """Возвращает (action, trigger_msg_id_to_delete, need_sub_warning)."""
        if is_user_banned(user_id, username):
            return 'banned', None, False

        cleaned = text.strip().lower()
        is_trigger = (cleaned == self.trigger)

        rec = self.participants.get(user_id)
        if not rec:
            rec = {
                'username': username,
                'valid': False,
                'disqualified': False,
                'non_trigger_count': 0,
                'has_trigger': False,
                'trigger_msg_id': None
            }
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
                self.valid_order.append(user_id)
                return 'valid', None, True
            else:
                return 'no_username', None, False
        else:
            rec['non_trigger_count'] += 1
            if rec['non_trigger_count'] >= 2:
                rec['disqualified'] = True
                return 'disqualified', rec.get('trigger_msg_id'), False
            else:
                return 'extra_ignored', None, False

    async def finalize(self, bot: Bot) -> List[int]:
        """Возвращает финальный список user_id, удаляя триггеры исключённых."""
        final = []
        for uid in self.valid_order:
            rec = self.participants.get(uid)
            if not rec or rec['disqualified'] or not rec['valid']:
                continue
            username = rec['username']
            if not username:
                try:
                    member = await bot.get_chat_member(self.chat_id, uid)
                    username = member.user.username
                except:
                    pass
            if not username or not await check_subscriptions(bot, uid) or is_user_banned(uid, username):
                # Удаляем триггер исключённого
                if rec.get('trigger_msg_id'):
                    try:
                        await bot.delete_message(self.chat_id, rec['trigger_msg_id'])
                    except:
                        pass
                continue
            final.append(uid)
        return final

active_sessions: Dict[int, RouletteSession] = {}

# ---------- Роутеры ----------
admin_router = Router()
filter_router = Router()

# ---------- /start ----------
@admin_router.message(Command('start'))
async def start_cmd(message: types.Message, bot: Bot):
    if message.chat.type != 'private':
        return
    if message.from_user.id == MAIN_ADMIN_ID:
        await menu(message)

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
    prizes_str = get_setting('prizes') or '[]'
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
    rid = save_roulette(chat_id, 'waiting_start', duration, winners or 0,
                        trigger, prizes_str, get_setting('rules'),
                        get_setting('start_msg'), get_setting('stop_msg'),
                        get_setting('result_msg'), start_time, stop_time,
                        seed=seed, seed_hash=seed_hash)
    announce = (
        f"📢 Рулетка:\n"
        f"Победителей: {winners if winners else 'нет (админ сам)'}\n"
        f"Длительность: {duration} мин.\n"
        f"Старт: {start_time.strftime('%d.%m.%Y %H:%M')} (НСК)\n"
        f"🔒 Хеш честности: {seed_hash}"
    )
    enqueue(chat_id, 'send_message', text=announce)
    if start_time > now:
        asyncio.create_task(schedule_start(bot, chat_id, rid, (start_time - now).total_seconds()))
    else:
        await start_recording(bot, chat_id, rid)

# ---------- @отмена ----------
@admin_router.message(F.text.regexp(r'@отмена'))
async def cancel_cmd(message: types.Message, bot: Bot):
    if not await is_admin(bot, message.chat.id, message.from_user.id):
        return
    chat_id = message.chat.id
    session = active_sessions.pop(chat_id, None)
    if session:
        # Удаляем все триггеры участников
        for uid, rec in session.participants.items():
            if rec.get('trigger_msg_id'):
                try:
                    await bot.delete_message(chat_id, rec['trigger_msg_id'])
                except:
                    pass
        enqueue(chat_id, 'send_message', text="❌ Рулетка отменена.")
        update_roulette(session.roulette_id, status='cancelled')
    else:
        # Проверить запланированную рулетку
        roulette = get_roulette(chat_id, 'waiting_start')
        if roulette:
            update_roulette(roulette['id'], status='cancelled')
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
    parts = args.split()
    for p in parts:
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
    numbers = list(range(lo, hi+1))
    winners = select_winners(numbers, winners_count, seed)
    img = create_random_image(winners, lo, hi, datetime.now(NOVOSIBIRSK), seed_hash)
    # Отправляем картинку без подписи
    await bot.send_photo(chat_id, photo=img)
    enqueue(chat_id, 'send_message', text=f"🔒 Хеш: {seed_hash}\nSeed: {seed}")
    enqueue(chat_id, 'send_message', text=get_verification_instruction(0, seed, [str(n) for n in numbers], [str(w) for w in winners]))

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
    # Номера победителей (1-based)
    winner_numbers = [i+1 for i in final_winners]
    img = create_result_image(winner_numbers, len(participants), datetime.now(NOVOSIBIRSK), seed_hash)
    prizes_list = json.loads(last['prizes']) if last['prizes'] else []
    wstr = [f"{num}. {names[i]} (приз: {prizes_list[i] if i < len(prizes_list) else 'не указан'})"
            for i, num in zip(final_winners, winner_numbers)]
    result = last['result_msg'].replace('{winners}', "\n".join(wstr))
    if old_names:
        result += "\n\nЗачёркнутые лишились призов: " + ", ".join(f"<s>{n}</s>" for n in old_names)
    await bot.send_photo(chat_id, photo=img, caption=result)
    enqueue(chat_id, 'send_message', text=f"🔒 Хеш: {seed_hash}\nSeed: {seed}")
    enqueue(chat_id, 'send_message', text=get_verification_instruction(last['id'], seed, names, [str(num) for num in winner_numbers]))
    new_id = save_roulette(chat_id, 'finished', last['duration'], len(final_winners),
                           last['trigger'], last['prizes'], last['rules'], last['start_msg'],
                           last['stop_msg'], last['result_msg'], datetime.now(NOVOSIBIRSK),
                           datetime.now(NOVOSIBIRSK), seed=seed, seed_hash=seed_hash)
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
    rules = roulette['rules']
    if rules:
        await send_template(bot, chat_id, rules, trigger=roulette['trigger'],
                            duration=str(roulette['duration']), seed_hash=roulette.get('seed_hash',''))
    start = roulette['start_msg']
    if start:
        await send_template(bot, chat_id, start, trigger=roulette['trigger'])
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
    valid_users = await session.finalize(bot)
    valid_users.sort(key=lambda uid: session.participants[uid]['trigger_msg_id'])
    names = []
    for uid in valid_users:
        try:
            m = await bot.get_chat_member(chat_id, uid)
            names.append(m.user.username)  # без @
        except:
            names.append(str(uid))
    participants_str = "\n".join(f"{i+1}. {n}" for i, n in enumerate(names))
    enqueue(chat_id, 'send_message', text=f"📋 Участники ({len(valid_users)}):\n{participants_str}")
    try:
        await bot.send_message(MAIN_ADMIN_ID, f"Список участников чата {chat_id}:\n{participants_str}")
    except:
        pass
    if roulette['winners_count'] > 0:
        seed = roulette['seed']
        winners = select_winners(valid_users, roulette['winners_count'], seed)
        winner_numbers = [valid_users.index(u)+1 for u in winners]
        wnames = [names[valid_users.index(u)] for u in winners]
        img = create_result_image(winner_numbers, len(valid_users), datetime.now(NOVOSIBIRSK), roulette['seed_hash'])
        prizes = json.loads(roulette['prizes']) if roulette['prizes'] else []
        wstr = [f"{num}. {name} (приз: {prizes[i] if i < len(prizes) else 'не указан'})"
                for num, name in zip(winner_numbers, wnames)]
        result_text = roulette['result_msg'].replace('{winners}', "\n".join(wstr))
        await bot.send_photo(chat_id, photo=img, caption=result_text)
        enqueue(chat_id, 'send_message', text=f"🔒 Хеш: {roulette['seed_hash']}\nSeed: {seed}")
        enqueue(chat_id, 'send_message', text=get_verification_instruction(rid, seed, names, [str(num) for num in winner_numbers]))
        update_roulette(rid, status='finished', participants_json=json.dumps(valid_users),
                        winners_json=json.dumps([valid_users.index(u) for u in winners]))
    else:
        update_roulette(rid, status='finished', participants_json=json.dumps(valid_users))
        enqueue(chat_id, 'send_message', text="Админ, проведите розыгрыш самостоятельно.")
    for uid, rec in session.participants.items():
        if rec.get('disqualified'):
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
            await message.reply("⚠️ Вы не подписаны на обязательные каналы. Подпишитесь до конца записи, иначе ваш голос не зачтётся.")
        return
    elif action == 'no_username':
        await message.reply("⚠️ Нужен @username. Установите до конца записи.")
    elif action == 'disqualified':
        await message.delete()
        if trigger_to_delete:
            try:
                await bot.delete_message(message.chat.id, trigger_to_delete)
            except:
                pass
        await mute_user(bot, message.chat.id, user_id)
        mention = f"@{username}" if username else message.from_user.full_name
        enqueue(message.chat.id, 'send_message', text=f"⛔ {mention} дисквалифицирован.")
    elif action == 'extra_ignored':
        await message.delete()
    elif action == 'ignored':
        await message.delete()
    elif action == 'banned':
        await message.delete()
        await mute_user(bot, message.chat.id, user_id)
        mention = f"@{username}" if username else message.from_user.full_name
        enqueue(message.chat.id, 'send_message', text=f"🚫 {mention}, вы забанены.")

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
    kb.button(text="💬 Каналы подписки", callback_data="channels_menu")
    kb.button(text="🚫 Баны", callback_data="ban_menu")
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
    s = f"""<b>Текущие настройки:</b>
Триггер: {get_setting('trigger')}
Длительность: {get_setting('duration')} мин
Макс. участников: {get_setting('max_participants') or 'нет'}
Чат: {get_setting('chat_id') or 'не задан'}
Каналы: {', '.join(get_channels()) or 'нет'}
Призы: {get_setting('prizes') or 'нет'}
Правила: {format_setting(get_setting('rules'))}
Старт: {format_setting(get_setting('start_msg'))}
Стоп: {format_setting(get_setting('stop_msg'))}
Результат: {format_setting(get_setting('result_msg'))}"""
    await call.message.edit_text(s, reply_markup=back_btn(), parse_mode='HTML')
    await call.answer()

# ---------- Обработчики настроек (каждый с FSM) ----------
@admin_router.callback_query(F.data == "set_chat")
async def set_chat_start(call: types.CallbackQuery, state: FSMContext):
    await call.message.edit_text("Введите ID чата (текущий: " +
                                 (get_setting('chat_id') or 'не задан') + ")", reply_markup=back_btn())
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
                                 get_setting('duration') + "):", reply_markup=back_btn())
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
                                 get_setting('trigger') + "»):", reply_markup=back_btn())
    await state.set_state(SettingsForm.waiting_for_trigger)
    await call.answer()

@admin_router.message(StateFilter(SettingsForm.waiting_for_trigger))
async def set_trigger_finish(message: types.Message, state: FSMContext):
    new_trigger = message.text.strip() if message.text else ""
    if new_trigger:
        set_setting('trigger', new_trigger)
        await message.answer(f"Триггер: «{new_trigger}»", reply_markup=back_btn())
    else:
        await message.answer("Не может быть пустым.", reply_markup=back_btn())
    await state.clear()

@admin_router.callback_query(F.data == "set_prizes")
async def set_prizes_start(call: types.CallbackQuery, state: FSMContext):
    await call.message.edit_text("Введите призы в формате JSON-списка (сейчас " +
                                 (get_setting('prizes') or '[]') + "):", reply_markup=back_btn())
    await state.set_state(SettingsForm.waiting_for_prizes)
    await call.answer()

@admin_router.message(StateFilter(SettingsForm.waiting_for_prizes))
async def set_prizes_finish(message: types.Message, state: FSMContext):
    try:
        prizes = json.loads(message.text)
        if isinstance(prizes, list):
            set_setting('prizes', json.dumps(prizes, ensure_ascii=False))
            await message.answer("Призы сохранены.", reply_markup=back_btn())
        else:
            raise ValueError
    except:
        await message.answer("Неверный формат. Введите JSON-список.", reply_markup=back_btn())
    await state.clear()

@admin_router.callback_query(F.data == "set_rules")
async def set_rules_start(call: types.CallbackQuery, state: FSMContext):
    await call.message.edit_text("Отправьте текст правил или перешлите готовое сообщение.",
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
    await call.message.edit_text("Отправьте стартовое сообщение или перешлите готовое.",
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
    await call.message.edit_text("Отправьте стоп-сообщение или перешлите готовое.",
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
    await call.message.edit_text("Отправьте шаблон результата (можно с {winners}) или перешлите готовое.",
                                 reply_markup=back_btn())
    await state.set_state(SettingsForm.waiting_for_result_msg)
    await call.answer()

@admin_router.message(StateFilter(SettingsForm.waiting_for_result_msg))
async def set_result_msg_finish(message: types.Message, state: FSMContext):
    data = save_media_template(message)
    set_setting('result_msg', data)
    await message.answer("Пост победителей сохранён.", reply_markup=back_btn())
    await state.clear()

@admin_router.callback_query(F.data == "channels_menu")
async def channels_menu(call: types.CallbackQuery):
    kb = InlineKeyboardBuilder()
    kb.button(text="➕ Добавить канал", callback_data="channel_add")
    kb.button(text="➖ Удалить канал", callback_data="channel_del")
    kb.button(text="« Назад", callback_data="back_to_menu")
    await call.message.edit_text("Каналы: " + ", ".join(get_channels() or ["нет"]),
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
    kb.button(text="🚫 Забанить", callback_data="ban_add")
    kb.button(text="📜 Список банов", callback_data="ban_list")
    kb.button(text="« Назад", callback_data="back_to_menu")
    await call.message.edit_text("Управление банами.", reply_markup=kb.as_markup())
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
    await message.answer(f"Пользователь {user_ident} забанен на {days} дн.", reply_markup=back_btn())
    await state.clear()

@admin_router.callback_query(F.data == "ban_list")
async def ban_list_view(call: types.CallbackQuery):
    with get_conn() as conn:
        rows = conn.execute("SELECT * FROM banned_users WHERE banned_until > ?",
                            (datetime.now(),)).fetchall()
    if rows:
        text = "Активные баны:\n" + "\n".join(
            f"- {'@'+r['username'] if r['username'] else r['user_id']} до {r['banned_until'][:19]} ({r['reason']})"
            for r in rows
        )
    else:
        text = "Нет активных банов."
    await call.message.edit_text(text, reply_markup=back_btn())
    await call.answer()

@admin_router.callback_query(F.data == "set_max")
async def set_max_start(call: types.CallbackQuery, state: FSMContext):
    await call.message.edit_text("Введите максимум участников (0 — без ограничения). Сейчас: " +
                                 (get_setting('max_participants') or '0'), reply_markup=back_btn())
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
