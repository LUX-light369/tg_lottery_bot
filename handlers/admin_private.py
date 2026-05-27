import datetime
import json
import zoneinfo
from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.filters import CommandStart
from aiogram.fsm.context import FSMContext
from aiogram.fsm.state import StatesGroup, State

from config import ADMIN_ID, DEFAULT_TZ
from database import async_session, BotConfig, WinnerCooldown, GiveawayPost
from sqlalchemy import select, update

router = Router()
tz_nsk = zoneinfo.ZoneInfo(DEFAULT_TZ)

class ConfigStates(StatesGroup):
    edit_start = State()
    edit_stop = State()
    edit_winners = State()
    edit_prizes = State()
    edit_trigger = State()
    add_cooldown = State()

class GiveawayCreate(StatesGroup):
    text = State()
    channels = State()
    task = State()
    end_type = State()
    end_val = State()
    winners = State()
    target_chat = State()

@router.message(CommandStart(), F.chat.type == "private")
async def admin_start_panel(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID: return
    await state.clear()
    
    builder = InlineKeyboardBuilder()
    builder.button(text="⚙️ Настройки текстов Рулетки", callback_data="cfg_roulette")
    builder.button(text="🎫 Создать Розыгрыш (Giveaway)", callback_data="cfg_giveaway")
    builder.button(text="🚫 Ограничить победителя", callback_data="cfg_cooldown")
    builder.adjust(1)
    
    await message.answer("🛠 **ГЛАВНАЯ ПАНЕЛЬ АДМИНИСТРАТОРА**\nВыберите модуль для настройки:", reply_markup=builder.as_markup(), parse_mode="Markdown")

# --- БЛОК РЕДАКТИРОВАНИЯ НАСТРОЕК РУЛЕТКИ ---
@router.callback_query(F.data == "cfg_roulette")
async def cfg_roulette(callback: CallbackQuery):
    async with async_session() as s:
        cfg = (await s.execute(select(BotConfig).where(BotConfig.id == 1))).scalar_one()
    
    builder = InlineKeyboardBuilder()
    builder.button(text="📝 Текст Старта", callback_data="edit_r_start")
    builder.button(text="📝 Текст Стопа", callback_data="edit_r_stop")
    builder.button(text="📝 Шаблон победы", callback_data="edit_r_win")
    builder.button(text="🎁 Призы по умолчанию", callback_data="edit_r_prizes")
    builder.button(text="🎯 Изменить триггер (+)", callback_data="edit_r_trigger")
    builder.button(text="🔙 Назад", callback_data="back_root")
    builder.adjust(1)
    
    status = (
        f"⚙️ **Текущие шаблоны рулетки:**\n\n"
        f"• **Триггер записи:** `{cfg.r_trigger}`\n"
        f"• **Призы:** `{cfg.r_default_prizes}`\n"
        f"• **Старт:** {cfg.r_start_msg}\n"
    )
    await callback.message.edit_text(status, reply_markup=builder.as_markup(), parse_mode="Markdown")

@router.callback_query(F.data == "back_root")
async def back_root(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await admin_start_panel(callback.message, state)

@router.callback_query(F.data == "edit_r_start")
async def edit_r_start(callback: CallbackQuery, state: FSMContext):
    await state.set_state(ConfigStates.edit_start)
    await callback.message.edit_text("Отправьте новый text стартового сообщения. Используйте `{trigger}` для подстановки символа записи:")

@router.message(ConfigStates.edit_start)
async def save_start_msg(message: Message, state: FSMContext):
    async with async_session() as s:
        await s.execute(update(BotConfig).where(BotConfig.id == 1).values(r_start_msg=message.html_text))
        await s.commit()
    await state.clear()
    await message.answer("✅ Шаблон стартового сообщения обновлен!")

@router.callback_query(F.data == "edit_r_trigger")
async def edit_r_trigger(callback: CallbackQuery, state: FSMContext):
    await state.set_state(ConfigStates.edit_trigger)
    await callback.message.edit_text("Отправьте новый символ или эмодзи триггера (например `+`, `🎲`, `участвую`):")

@router.message(ConfigStates.edit_trigger)
async def save_trigger(message: Message, state: FSMContext):
    trigger = message.text.strip()
    async with async_session() as s:
        await s.execute(update(BotConfig).where(BotConfig.id == 1).values(r_trigger=trigger))
        await s.commit()
    await state.clear()
    await message.answer(f"✅ Триггер записи изменен на `{trigger}`!")

# --- ОГРАНИЧЕНИЕ ПОБЕДИТЕЛЕЙ ---
@router.callback_query(F.data == "cfg_cooldown")
async def cfg_cooldown(callback: CallbackQuery, state: FSMContext):
    await state.set_state(ConfigStates.add_cooldown)
    await callback.message.edit_text("Введите юзернейм игрока и количество дней бана через пробел.\nПример: `UserVasya 7`")

@router.message(ConfigStates.add_cooldown)
async def save_cooldown(message: Message, state: FSMContext):
    try:
        username, days = message.text.split()
        username = username.lstrip("@")
        days_int = int(days)
    except:
        await message.answer("❌ Ошибка ввода. Формат: `ИмяПользователя ЧислоДней`")
        return
        
    until = datetime.datetime.now(tz_nsk) + datetime.timedelta(days=days_int)
    async with async_session() as s:
        await s.merge(WinnerCooldown(username=username, until_date=until.replace(tzinfo=None)))
        await s.commit()
        
    await state.clear()
    await message.answer(f"✅ Пользователь @{username} заблокирован в выигрышах на {days_int} дней (до {until.strftime('%d.%m %H:%M')})")

# --- БЛОК СОЗДАНИЯ РОЗЫГРЫШЕЙ (GIVEAWAY) ---
@router.callback_query(F.data == "cfg_giveaway")
async def start_giveaway_fsm(callback: CallbackQuery, state: FSMContext):
    await state.set_state(GiveawayCreate.text)
    await callback.message.edit_text("🎫 **Создание Розыгрыша.**\nОтправьте текст поста. Вы можете прикрепить к нему изображение/медиа и использовать форматирование:")

@router.message(GiveawayCreate.text)
async def process_g_text(message: Message, state: FSMContext):
    media_id = None
    if message.photo: media_id = message.photo[-1].file_id
    elif message.video: media_id = message.video.file_id
    
    await state.update_data(text=message.html_text or message.text, media_id=media_id)
    await state.set_state(GiveawayCreate.channels)
    await message.answer("Перечислите юзернеймы каналов для обязательной подписки через запятую (например: `@chan1, @chan2`). Если подписка не нужна, напишите `0`:")

@router.message(GiveawayCreate.channels)
async def process_g_channels(message: Message, state: FSMContext):
    txt = message.text.strip()
    channels = "" if txt == "0" else ",".join([c.strip().lstrip("@") for c in txt.split(",")])
    await state.update_data(channels=channels)
    await state.set_state(GiveawayCreate.task)
    await message.answer("Укажите ссылку на кастомное доп. задание (реф. ссылка). Если задания нет, отправьте `0`:")

@router.message(GiveawayCreate.task)
async def process_g_task(message: Message, state: FSMContext):
    txt = message.text.strip()
    task = None if txt == "0" else txt
    await state.update_data(task=task)
    
    builder = InlineKeyboardBuilder()
    builder.button(text="⏱ По времени", callback_data="g_type_time")
    builder.button(text="👥 По числу участников", callback_data="g_type_users")
    await message.answer("Выберите критерий завершения розыгрыша:", reply_markup=builder.as_markup())

@router.callback_query(F.data.startswith("g_type_"))
async def process_g_type(callback: CallbackQuery, state: FSMContext):
    g_type = callback.data.split("_")[2]
    await state.update_data(end_type=g_type)
    await state.set_state(GiveawayCreate.end_val)
    if g_type == "time":
        await callback.message.edit_text("Укажите время завершения в формате ЧЧ:ММ (по Новосибирску):")
    else:
        await callback.message.edit_text("Укажите количество участников для стопа (например `100`):")

@router.message(GiveawayCreate.end_val)
async def process_g_val(message: Message, state: FSMContext):
    await state.update_data(end_value=message.text.strip())
    await state.set_state(GiveawayCreate.winners)
    await message.answer("Укажите количество победителей (число):")

@router.message(GiveawayCreate.winners)
async def process_g_winners(message: Message, state: FSMContext):
    await state.update_data(winners=int(message.text.strip()))
    await state.set_state(GiveawayCreate.target_chat)
    await message.answer("Отправьте числовой ID группы/чата, куда выложить пост розыгрыша:")

@router.message(GiveawayCreate.target_chat)
async def process_g_finalize(message: Message, state: FSMContext, bot: Bot):
    data = await state.get_data()
    chat_id = int(message.text.strip())
    
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🟢 Участвовать (0)", callback_data="g_join_active")]
    ])
    
    sent_msg = None
    if data['media_id']:
        sent_msg = await bot.send_photo(chat_id, photo=data['media_id'], caption=data['text'], reply_markup=kb, parse_mode="HTML")
    else:
        sent_msg = await bot.send_message(chat_id, text=data['text'], reply_markup=kb, parse_mode="HTML")
        
    async with async_session() as s:
        s.add(GiveawayPost(
            chat_id=chat_id,
            message_id=sent_msg.message_id,
            text_data=data['text'],
            media_file_id=data['media_id'],
            channels_to_check=data['channels'],
            task_url=data['task'],
            end_type=data['end_type'],
            end_value=data['end_value'],
            winners_count=data['winners'],
            is_active=True
        ))
        await s.commit()
        
    await state.clear()
    await message.answer("🚀 Пост розыгрыша успешно опубликован в канале/группе!")
