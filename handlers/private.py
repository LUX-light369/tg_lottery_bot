from aiogram import Router, F, Bot
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import State, StatesGroup
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import Command, StateFilter
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from database.models import Giveaway, ChatSettings, Restriction
from services.checks import is_main_admin, get_chat_settings
from services.giveaway import start_giveaway
from utils.helpers import generate_seed, get_md5_hash
import json

router = Router()

class GiveawayForm(StatesGroup):
    choose_chat = State()
    post = State()
    channels = State()
    extra = State()
    mode = State()
    time_or_count = State()
    winners = State()
    prizes = State()
    confirm = State()

class SettingsFSM(StatesGroup):
    waiting_chat_id = State()
    waiting_value = State()

# Главное меню
@router.message(Command("settings"))
async def main_menu(message: Message, bot: Bot):
    if not is_main_admin(message.from_user.id):
        await message.answer("⛔ Доступ запрещён.")
        return
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🛠 Настройка рулетки", callback_data="settings_roulette")],
        [InlineKeyboardButton(text="🛠 Настройка розыгрыша", callback_data="settings_giveaway")],
        [InlineKeyboardButton(text="🎁 Создать розыгрыш", callback_data="create_giveaway")],
        [InlineKeyboardButton(text="🔄 Перекрут розыгрыша", callback_data="reroll_giveaway")],
        [InlineKeyboardButton(text="📋 Список ограничений", callback_data="list_restrictions")],
    ])
    await message.answer("⚙️ Главное меню", reply_markup=keyboard)

@router.callback_query(F.data == "create_giveaway")
async def cb_create_giveaway(call: CallbackQuery, state: FSMContext, bot: Bot):
    await call.message.edit_text("Введите ID чата/канала, куда отправить розыгрыш:")
    await state.set_state(GiveawayForm.choose_chat)
    await call.answer()

@router.message(GiveawayForm.choose_chat)
async def process_chat(message: Message, state: FSMContext, bot: Bot):
    try:
        chat_id = int(message.text)
    except:
        await message.answer("Некорректный ID чата. Попробуйте ещё раз.")
        return
    try:
        member = await bot.get_chat_member(chat_id, bot.id)
        if member.status not in ("administrator", "creator"):
            raise
    except:
        await message.answer("Бот не является администратором в этом чате.")
        return
    await state.update_data(chat_id=chat_id)
    await message.answer("Отправьте пост розыгрыша (текст с форматированием, можно прикрепить медиа).")
    await state.set_state(GiveawayForm.post)

@router.message(GiveawayForm.post, F.content_type.in_({'text', 'photo', 'video', 'animation'}))
async def process_post(message: Message, state: FSMContext, bot: Bot):
    await state.update_data(
        post_text=message.html_text if message.text else message.caption,
        post_media=message.photo[-1].file_id if message.photo else (message.video.file_id if message.video else (message.animation.file_id if message.animation else None))
    )
    await message.answer("Введите username каналов для проверки подписки через запятую (без @), или 0 если не нужно.")
    await state.set_state(GiveawayForm.channels)

@router.message(GiveawayForm.channels)
async def process_channels(message: Message, state: FSMContext):
    if message.text.strip() == "0":
        await state.update_data(check_channels=[])
    else:
        chs = [ch.strip().lstrip("@") for ch in message.text.split(",") if ch.strip()]
        await state.update_data(check_channels=chs)
    await message.answer("Дополнительное условие (ссылка, задание) или 0 для пропуска.")
    await state.set_state(GiveawayForm.extra)

@router.message(GiveawayForm.extra)
async def process_extra(message: Message, state: FSMContext):
    extra = message.text if message.text != "0" else None
    await state.update_data(extra_condition=extra)
    await message.answer("Режим розыгрыша:\n/time — по времени\n/participants — по количеству участников")
    await state.set_state(GiveawayForm.mode)

@router.message(GiveawayForm.mode, F.text.in_(['/time', '/participants']))
async def process_mode(message: Message, state: FSMContext):
    mode = message.text[1:]
    await state.update_data(mode=mode)
    if mode == "time":
        await message.answer("Введите дату и время окончания в формате ДД.ММ.ГГГГ ЧЧ:ММ")
    else:
        await message.answer("Введите максимальное количество участников.")
    await state.set_state(GiveawayForm.time_or_count)

@router.message(GiveawayForm.time_or_count)
async def process_time_count(message: Message, state: FSMContext):
    data = await state.get_data()
    mode = data['mode']
    if mode == "time":
        from datetime import datetime
        try:
            end_time = datetime.strptime(message.text, "%d.%m.%Y %H:%M")
        except:
            await message.answer("Неверный формат. Попробуйте ещё раз.")
            return
        await state.update_data(end_time=end_time)
    else:
        if not message.text.isdigit():
            await message.answer("Введите число.")
            return
        await state.update_data(max_participants=int(message.text))
    await message.answer("Количество победителей:")
    await state.set_state(GiveawayForm.winners)

@router.message(GiveawayForm.winners)
async def process_winners(message: Message, state: FSMContext):
    if not message.text.isdigit():
        await message.answer("Введите число.")
        return
    await state.update_data(winner_count=int(message.text))
    await message.answer("Введите призы через запятую (первый — для 1-го места и т.д.).")
    await state.set_state(GiveawayForm.prizes)

@router.message(GiveawayForm.prizes)
async def process_prizes(message: Message, state: FSMContext, bot: Bot):
    prizes = [p.strip() for p in message.text.split(",") if p.strip()]
    data = await state.get_data()
    winner_count = data['winner_count']
    if len(prizes) < winner_count:
        prizes = [prizes[0]] * winner_count
    elif len(prizes) > winner_count:
        prizes = prizes[:winner_count]
    await state.update_data(prizes=prizes)
    summary = (
        f"📋 **Розыгрыш**\n"
        f"Чат: {data['chat_id']}\n"
        f"Режим: {data['mode']}\n"
        f"Победителей: {winner_count}\n"
        f"Призы: {', '.join(prizes)}\n"
        f"Каналы: {', '.join(data['check_channels']) if data['check_channels'] else 'нет'}\n"
        f"Доп.условие: {data['extra_condition'] or 'нет'}\n"
    )
    if data['mode'] == 'time':
        summary += f"Окончание: {data['end_time']}\n"
    else:
        summary += f"Макс.участников: {data['max_participants']}\n"
    await message.answer(summary + "\nПодтвердите командой /confirm или /cancel.")
    await state.set_state(GiveawayForm.confirm)

@router.message(GiveawayForm.confirm, Command("confirm"))
async def confirm_giveaway(message: Message, state: FSMContext, bot: Bot, session: AsyncSession):
    data = await state.get_data()
    seed = generate_seed()
    giveaway = Giveaway(
        chat_id=data['chat_id'],
        creator_id=message.from_user.id,
        mode=data['mode'],
        end_time=data.get('end_time'),
        max_participants=data.get('max_participants'),
        winner_count=data['winner_count'],
        prizes=data['prizes'],
        seed=seed,
        seed_hash=get_md5_hash(seed),
        check_channels=data['check_channels'],
        extra_condition=data['extra_condition'],
        post_text=data['post_text'],
        post_media=data['post_media'],
        status='active'
    )
    session.add(giveaway)
    await session.commit()
    await start_giveaway(giveaway, bot)
    await message.answer("Розыгрыш запущен!")
    await state.clear()

@router.message(Command("cancel"), StateFilter("*"))
async def cancel_fsm(message: Message, state: FSMContext):
    await state.clear()
    await message.answer("Отменено.")

# === Настройки через inline ===

@router.callback_query(F.data.in_(['settings_roulette', 'settings_giveaway']))
async def start_settings(call: CallbackQuery, state: FSMContext):
    module = call.data.split("_")[1]
    await state.update_data(module=module)
    await call.message.edit_text("Введите ID чата для настройки:")
    await state.set_state(SettingsFSM.waiting_chat_id)
    await call.answer()

@router.message(SettingsFSM.waiting_chat_id)
async def process_chat_id(message: Message, state: FSMContext, bot: Bot, session: AsyncSession):
    try:
        chat_id = int(message.text)
    except:
        await message.answer("Некорректный ID.")
        return
    try:
        member = await bot.get_chat_member(chat_id, bot.id)
        if member.status not in ("administrator", "creator"):
            raise
    except:
        await message.answer("Бот не админ в этом чате.")
        return
    await state.update_data(chat_id=chat_id)
    data = await state.get_data()
    module = data['module']
    settings = await get_chat_settings(session, chat_id, module)
    text = f"Текущие настройки {module} для чата {chat_id}:\n" + json.dumps(settings, ensure_ascii=False, indent=2)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Изменить время записи (рулетка)", callback_data="edit_duration")],
        [InlineKeyboardButton(text="Изменить призы", callback_data="edit_prizes")],
        [InlineKeyboardButton(text="Изменить триггеры (рулетка)", callback_data="edit_triggers")],
        [InlineKeyboardButton(text="Изменить стартовое сообщение", callback_data="edit_start_msg")],
        [InlineKeyboardButton(text="Изменить стоп сообщение", callback_data="edit_stop_msg")],
        [InlineKeyboardButton(text="Изменить дни бана победителей", callback_data="edit_ban_days")],
        [InlineKeyboardButton(text="Сохранить и выйти", callback_data="save_settings")],
    ])
    await message.answer(text, reply_markup=keyboard)
    await state.set_state(None)

@router.callback_query(F.data.startswith("edit_"))
async def edit_setting(call: CallbackQuery, state: FSMContext, bot: Bot):
    param = call.data[5:]
    await call.message.edit_text(f"Введите новое значение для {param}:")
    await state.update_data(editing_param=param)
    await state.set_state(SettingsFSM.waiting_value)
    await call.answer()

@router.message(SettingsFSM.waiting_value)
async def process_new_value(message: Message, state: FSMContext, bot: Bot, session: AsyncSession):
    data = await state.get_data()
    param = data['editing_param']
    chat_id = data['chat_id']
    module = data['module']
    new_value = message.text
    if param == "duration":
        new_value = int(new_value)
    elif param == "ban_days":
        new_value = int(new_value)
    elif param in ("prizes", "triggers"):
        new_value = [x.strip() for x in new_value.split(",") if x.strip()]
    stmt = select(ChatSettings).where(ChatSettings.chat_id == chat_id, ChatSettings.module == module)
    res = await session.execute(stmt)
    settings = res.scalars().first()
    if not settings:
        settings = ChatSettings(chat_id=chat_id, module=module, data={})
        session.add(settings)
    settings.data[param] = new_value
    await session.commit()
    await message.answer(f"Значение {param} обновлено.")
    await show_settings_menu(message, chat_id, module, bot, state, session)

async def show_settings_menu(message, chat_id, module, bot, state, session: AsyncSession):
    settings = await get_chat_settings(session, chat_id, module)
    text = f"Текущие настройки {module} для чата {chat_id}:\n" + json.dumps(settings, ensure_ascii=False, indent=2)
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="Изменить время записи (рулетка)", callback_data="edit_duration")],
        [InlineKeyboardButton(text="Изменить призы", callback_data="edit_prizes")],
        [InlineKeyboardButton(text="Изменить триггеры (рулетка)", callback_data="edit_triggers")],
        [InlineKeyboardButton(text="Изменить стартовое сообщение", callback_data="edit_start_msg")],
        [InlineKeyboardButton(text="Изменить стоп сообщение", callback_data="edit_stop_msg")],
        [InlineKeyboardButton(text="Изменить дни бана победителей", callback_data="edit_ban_days")],
        [InlineKeyboardButton(text="Сохранить и выйти", callback_data="save_settings")],
    ])
    await message.answer(text, reply_markup=keyboard)
    await state.clear()

@router.callback_query(F.data == "save_settings")
async def save_settings(call: CallbackQuery, state: FSMContext):
    await call.message.edit_text("Настройки сохранены.")
    await state.clear()
    await call.answer()
