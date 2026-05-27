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
from database import async_session, BotConfig, WinnerCooldown, GiveawayPost, SavedTargetChat, SavedCheckChannel
from sqlalchemy import select, update, delete

router = Router()
tz_nsk = zoneinfo.ZoneInfo(DEFAULT_TZ)

class ConfigStates(StatesGroup):
    edit_start = State()
    edit_stop = State()
    edit_winners = State()
    edit_prizes = State()
    edit_trigger = State()
    edit_duration = State() # Шаг FSM для времени записи по умолчанию
    add_cooldown = State()

class GiveawayCreate(StatesGroup):
    text = State()
    channels = State()
    task = State()
    end_type = State()
    end_val = State()
    winners = State()
    target_chat = State()

async def send_main_panel(message: Message):
    builder = InlineKeyboardBuilder()
    builder.button(text="⚙️ Настройки текстов Рулетки", callback_data="cfg_roulette")
    builder.button(text="🎫 Создать Розыгрыш (Giveaway)", callback_data="cfg_giveaway")
    builder.button(text="🛑 Отмена active Розыгрышей", callback_data="cfg_cancel_g")
    builder.button(text="🚫 Ограничить победителя", callback_data="cfg_cooldown")
    builder.adjust(1)
    await message.answer("🛠 **ГЛАВНАЯ ПАНЕЛЬ АДМИНИСТРАТОРА**\nВыберите модуль для настройки:", reply_markup=builder.as_markup(), parse_mode="Markdown")

@router.message(CommandStart(), F.chat.type == "private")
async def admin_start_panel(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID: 
        if message.text and message.text.startswith("/start g_"):
            g_id = int(message.text.split("g_")[1])
            await message.answer(f"👋 Привет! Ты перешел для участия в розыгрыше #{g_id}.\nНажми кнопку «Участвовать» в канале.")
        return
    await state.clear()
    await send_main_panel(message)

@router.callback_query(F.data == "cfg_roulette")
async def cfg_roulette(callback: CallbackQuery):
    async with async_session() as s:
        cfg = (await s.execute(select(BotConfig).where(BotConfig.id == 1))).scalar_one()
    
    builder = InlineKeyboardBuilder()
    builder.button(text="📝 Текст Старта", callback_data="edit_r_start")
    builder.button(text="📝 Текст Стопа", callback_data="edit_r_stop")
    builder.button(text="📝 Шаблон победы", callback_data="edit_r_win")
    builder.button(text="🎁 Призы по умолчанию", callback_data="edit_r_prizes")
    builder.button(text="🎯 Изменить триггер", callback_data="edit_r_trigger")
    builder.button(text="⏱ Время записи по ум.", callback_data="edit_r_duration")
    builder.button(text="🔙 Назад", callback_data="back_root")
    builder.adjust(2)
    
    status = (
        f"⚙️ **Текущие настройки рулетки:**\n\n"
        f"• **Триггер:** `{cfg.r_trigger}`\n"
        f"• **Время записи по ум.:** `{cfg.r_default_duration} мин`\n"
        f"• **Призы по ум.:** `{cfg.r_default_prizes}`\n"
        f"• **Старт:** {cfg.r_start_msg}\n"
        f"• **Стоп:** {cfg.r_stop_msg}\n"
        f"• **Победа:** {cfg.r_winner_template}"
    )
    await callback.message.edit_text(status, reply_markup=builder.as_markup(), parse_mode="HTML")

@router.callback_query(F.data == "back_root")
async def back_root(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    await callback.message.delete()
    await send_main_panel(callback.message)

@router.callback_query(F.data == "edit_r_duration")
async def edit_r_duration(callback: CallbackQuery, state: FSMContext):
    await state.set_state(ConfigStates.edit_duration)
    await callback.message.edit_text("Введите время записи для рулетки по умолчанию (в минутах, только число):")

@router.message(ConfigStates.edit_duration)
async def save_duration(message: Message, state: FSMContext):
    try:
        minutes = int(message.text.strip())
    except:
        await message.answer("❌ Введите корректное число минут!")
        return
        
    async with async_session() as s:
        await s.execute(update(BotConfig).where(BotConfig.id == 1).values(r_default_duration=minutes))
        await s.commit()
    await state.clear()
    await message.answer(f"✅ Время записи по умолчанию изменено на {minutes} мин.")
    await send_main_panel(message)

@router.callback_query(F.data == "edit_r_start")
async def edit_r_start(callback: CallbackQuery, state: FSMContext):
    await state.set_state(ConfigStates.edit_start)
    await callback.message.edit_text("Отправьте новый HTML текст стартового сообщения. Используйте `{trigger}`:")

@router.message(ConfigStates.edit_start)
async def save_start_msg(message: Message, state: FSMContext):
    # Безопасное извлечение форматирования во избежание None значений
    text_to_save = message.html_text or message.text or ""
    async with async_session() as s:
        await s.execute(update(BotConfig).where(BotConfig.id == 1).values(r_start_msg=text_to_save))
        await s.commit()
    await state.clear()
    await message.answer("✅ Шаблон стартового сообщения обновлен!")
    await send_main_panel(message)

@router.callback_query(F.data == "edit_r_stop")
async def edit_r_stop(callback: CallbackQuery, state: FSMContext):
    await state.set_state(ConfigStates.edit_stop)
    await callback.message.edit_text("Отправьте новый HTML текст сообщения об остановке записи:")

@router.message(ConfigStates.edit_stop)
async def save_stop_msg(message: Message, state: FSMContext):
    # Безопасное извлечение форматирования во избежание None значений
    text_to_save = message.html_text or message.text or ""
    async with async_session() as s:
        await s.execute(update(BotConfig).where(BotConfig.id == 1).values(r_stop_msg=text_to_save))
        await s.commit()
    await state.clear()
    await message.answer("✅ Шаблон сообщения стопа обновлен!")
    await send_main_panel(message)

@router.callback_query(F.data == "edit_r_win")
async def edit_r_win(callback: CallbackQuery, state: FSMContext):
    await state.set_state(ConfigStates.edit_winners)
    await callback.message.edit_text("Отправьте шаблон вывода победителей. Доступны переменные `{winners}` и `{default_prizes}`:")

@router.message(ConfigStates.edit_winners)
async def save_win_msg(message: Message, state: FSMContext):
    # Безопасное извлечение форматирования во избежание None значений
    text_to_save = message.html_text or message.text or ""
    async with async_session() as s:
        await s.execute(update(BotConfig).where(BotConfig.id == 1).values(r_winner_template=text_to_save))
        await s.commit()
    await state.clear()
    await message.answer("✅ Шаблон блока победителей сохранен!")
    await send_main_panel(message)

@router.callback_query(F.data == "edit_r_prizes")
async def edit_r_prizes(callback: CallbackQuery, state: FSMContext):
    await state.set_state(ConfigStates.edit_prizes)
    await callback.message.edit_text("Введите призы по умолчанию через запятую:")

@router.message(ConfigStates.edit_prizes)
async def save_prizes_msg(message: Message, state: FSMContext):
    async with async_session() as s:
        await s.execute(update(BotConfig).where(BotConfig.id == 1).values(r_default_prizes=message.text.strip()))
        await s.commit()
    await state.clear()
    await message.answer("✅ Дефолтные призы изменены.")
    await send_main_panel(message)

@router.callback_query(F.data == "edit_r_trigger")
async def edit_r_trigger(callback: CallbackQuery, state: FSMContext):
    await state.set_state(ConfigStates.edit_trigger)
    await callback.message.edit_text("Отправьте новый триггер (символ, текст или эмодзи вроде 👍):")

@router.message(ConfigStates.edit_trigger)
async def save_trigger(message: Message, state: FSMContext):
    trigger = message.text.strip()
    async with async_session() as s:
        await s.execute(update(BotConfig).where(BotConfig.id == 1).values(r_trigger=trigger))
        await s.commit()
    await state.clear()
    await message.answer(f"✅ Триггер изменен на `{trigger}`")
    await send_main_panel(message)

# --- МЕНЮ ОТМЕНЫ АКТИВНЫХ РОЗЫГРЫШЕЙ ---
@router.callback_query(F.data == "cfg_cancel_g")
async def cancel_giveaway_menu(callback: CallbackQuery):
    async with async_session() as s:
        active_posts = (await s.execute(select(GiveawayPost).where(GiveawayPost.is_active == True))).scalars().all()
    
    if not active_posts:
        await callback.answer("Нет активных розыгрышей для отмены!", show_alert=True)
        return
        
    builder = InlineKeyboardBuilder()
    for p in active_posts:
        builder.button(text=f"❌ Розыгрыш #{p.id} (Чат: {p.chat_id})", callback_data=f"del_g_{p.id}")
    builder.button(text="🔙 Назад", callback_data="back_root")
    builder.adjust(1)
    await callback.message.edit_text("Выберите розыгрыш, который хотите досрочно закрыть:", reply_markup=builder.as_markup())

@router.callback_query(F.data.startswith("del_g_"))
async def process_del_g(callback: CallbackQuery, bot: Bot):
    g_id = int(callback.data.split("_")[2])
    async with async_session() as s:
        post = (await s.execute(select(GiveawayPost).where(GiveawayPost.id == g_id))).scalar_one_or_none()
        if post:
            post.is_active = False
            await s.commit()
            try:
                await bot.edit_message_text(chat_id=post.chat_id, message_id=post.message_id, text="🛑 Розыгрыш отменен администратором.")
            except:
                try: await bot.delete_message(chat_id=post.chat_id, message_id=post.message_id)
                except: pass
    await callback.answer("Розыгрыш успешно аннулирован!")
    await cancel_giveaway_menu(callback)

# --- СОЗДАНИЕ GIVEAWAY ---
@router.callback_query(F.data == "cfg_giveaway")
async def start_giveaway_fsm(callback: CallbackQuery, state: FSMContext):
    await state.set_state(GiveawayCreate.text)
    await callback.message.edit_text("🎫 **Создание Розыгрыша.**\nОтправьте текст поста:")

@router.message(GiveawayCreate.text)
async def process_g_text(message: Message, state: FSMContext):
    media_id = None
    media_type = None
    if message.photo:
        media_id = message.photo[-1].file_id
        media_type = "photo"
    elif message.video:
        media_id = message.video.file_id
        media_type = "video"
        
    text_content = message.html_text or message.text or ""
    await state.update_data(text=text_content, media_id=media_id, media_type=media_type)
    
    async with async_session() as s:
        saved_ch = (await s.execute(select(SavedCheckChannel))).scalars().all()
        
    builder = InlineKeyboardBuilder()
    for ch in saved_ch:
        builder.button(text=f"📢 @{ch.username}", callback_data=f"select_ch_{ch.username}")
    builder.button(text="❌ Без проверок", callback_data="select_ch_0")
    builder.adjust(2)
    
    await state.set_state(GiveawayCreate.channels)
    await message.answer("Укажите каналы для проверки подписок через запятую или выберите сохраненные:", reply_markup=builder.as_markup())

@router.callback_query(GiveawayCreate.channels, F.data.startswith("select_ch_"))
async def process_g_channels_callback(callback: CallbackQuery, state: FSMContext):
    ch_val = callback.data.split("select_ch_")[1]
    await state.update_data(channels="" if ch_val == "0" else ch_val)
    await next_step_task(callback.message, state)

@router.message(GiveawayCreate.channels)
async def process_g_channels_text(message: Message, state: FSMContext):
    txt = message.text.replace("@", "").strip()
    channels = "" if txt == "0" else ",".join([c.strip() for c in txt.split(",")])
    if channels:
        async with async_session() as s:
            for c in channels.split(","): await s.merge(SavedCheckChannel(username=c.strip()))
            await s.commit()
    await state.update_data(channels=channels)
    await next_step_task(message, state)

async def next_step_task(message: Message, state: FSMContext):
    await state.set_state(GiveawayCreate.task)
    await message.answer("Укажите ссылку на задание или отправьте `0`:")

@router.message(GiveawayCreate.task)
async def process_g_task(message: Message, state: FSMContext):
    txt = message.text.strip()
    await state.update_data(task=None if txt == "0" else txt)
    builder = InlineKeyboardBuilder()
    builder.button(text="⏱ По времени", callback_data="g_type_time")
    builder.button(text="👥 По людям", callback_data="g_type_users")
    await message.answer("Тип завершения:", reply_markup=builder.as_markup())

@router.callback_query(F.data.startswith("g_type_"))
async def process_g_type(callback: CallbackQuery, state: FSMContext):
    g_type = callback.data.split("_")[2]
    await state.update_data(end_type=g_type)
    await state.set_state(GiveawayCreate.end_val)
    if g_type == "time":
        await callback.message.edit_text("Укажите время стопа (ЧЧ:ММ по НСК):")
    else:
        await callback.message.edit_text("Сколько людей должно набраться?")

@router.message(GiveawayCreate.end_val)
async def process_g_val(message: Message, state: FSMContext):
    await state.update_data(end_value=message.text.strip())
    await state.set_state(GiveawayCreate.winners)
    await message.answer("Число победителей:")

@router.message(GiveawayCreate.winners)
async def process_g_winners(message: Message, state: FSMContext):
    try: winners_count = int(message.text.strip())
    except: return
    await state.update_data(winners=winners_count)
    
    async with async_session() as s:
        saved_chats = (await s.execute(select(SavedTargetChat))).scalars().all()
    builder = InlineKeyboardBuilder()
    for sc in saved_chats: builder.button(text=f"💬 {sc.title}", callback_data=f"select_target_{sc.chat_id}")
    builder.adjust(1)
    
    await state.set_state(GiveawayCreate.target_chat)
    await message.answer("ID целевого чата/канала для публикации:", reply_markup=builder.as_markup())

@router.callback_query(GiveawayCreate.target_chat, F.data.startswith("select_target_"))
async def process_g_target_callback(callback: CallbackQuery, state: FSMContext, bot: Bot):
    chat_id = int(callback.data.split("select_target_")[2])
    await finalize_giveaway(chat_id, callback.message, state, bot)

@router.message(GiveawayCreate.target_chat)
async def process_g_target_text(message: Message, state: FSMContext, bot: Bot):
    try: chat_id = int(message.text.strip())
    except: return
    await finalize_giveaway(chat_id, message, state, bot)

async def finalize_giveaway(chat_id: int, message: Message, state: FSMContext, bot: Bot):
    data = await state.get_data()
    bot_info = await bot.get_me()
    try:
        chat_info = await bot.get_chat(chat_id)
        async with async_session() as s:
            await s.merge(SavedTargetChat(chat_id=chat_id, title=chat_info.title or f"Чат {chat_id}"))
            await s.commit()
    except: pass
    
    async with async_session() as s:
        new_post = GiveawayPost(
            chat_id=chat_id, message_id=0, text_data=data['text'],
            media_file_id=data['media_id'], channels_to_check=data['channels'],
            task_url=data['task'], end_type=data['end_type'],
            end_value=data['end_value'], winners_count=data['winners'], is_active=True
        )
        s.add(new_post)
        await s.flush()
        
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🟢 Участвовать (0)", url=f"https://t.me/{bot_info.username}?start=g_{new_post.id}")]
        ])
        
        if data['media_id']:
            if data['media_type'] == "photo": sent_msg = await bot.send_photo(chat_id, photo=data['media_id'], caption=data['text'], reply_markup=kb, parse_mode="HTML")
            else: sent_msg = await bot.send_video(chat_id, video=data['media_id'], caption=data['text'], reply_markup=kb, parse_mode="HTML")
        else:
            sent_msg = await bot.send_message(chat_id, text=data['text'], reply_markup=kb, parse_mode="HTML")
            
        new_post.message_id = sent_msg.message_id
        await s.commit()
    await state.clear()
    await message.answer("🚀 Розыгрыш опубликован!")
    await send_main_panel(message)

# --- БЛОК ОГРАНИЧЕНИЙ ---
@router.callback_query(F.data == "cfg_cooldown")
async def cfg_cooldown(callback: CallbackQuery, state: FSMContext):
    await state.set_state(ConfigStates.add_cooldown)
    await callback.message.edit_text("Юзернейм игрока и число дней бана через пробел:")

@router.message(ConfigStates.add_cooldown)
async def save_cooldown(message: Message, state: FSMContext):
    try:
        username, days = message.text.split()
        username = username.lstrip("@").strip()
        days_int = int(days)
    except: return
    until = datetime.datetime.now(tz_nsk) + datetime.timedelta(days=days_int)
    async with async_session() as s:
        await s.merge(WinnerCooldown(username=username, until_date=until.replace(tzinfo=None)))
        await s.commit()
    await state.clear()
    await message.answer("✅ Бан сохранен.")
    await send_main_panel(message)
