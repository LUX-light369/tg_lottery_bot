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
from sqlalchemy import select, update, delete

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

async def send_main_panel(message: Message):
    builder = InlineKeyboardBuilder()
    builder.button(text="⚙️ Настройки текстов Рулетки", callback_data="cfg_roulette")
    builder.button(text="🎫 Создать Розыгрыш (Giveaway)", callback_data="cfg_giveaway")
    builder.button(text="🛑 Отмена активных Розыгрышей", callback_data="cfg_cancel_g")
    builder.button(text="🚫 Ограничить победителя", callback_data="cfg_cooldown")
    builder.adjust(1)
    await message.answer("🛠 **ГЛАВНАЯ ПАНЕЛЬ АДМИНИСТРАТОРА**\nВыберите модуль для настройки:", reply_markup=builder.as_markup(), parse_mode="Markdown")

@router.message(CommandStart(), F.chat.type == "private")
async def admin_start_panel(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID: 
        # Проверяем, не перешел ли обычный юзер по реф-ссылке розыгрыша
        if message.text and message.text.startswith("/start g_"):
            g_id = int(message.text.split("g_")[1])
            await message.answer(f"👋 Привет! Ты перешел для участия в розыгрыше #{g_id}.\nНажми кнопку «Участвовать» в канале, чтобы я зафиксировал тебя в ЛС.")
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
    builder.button(text="🔙 Назад", callback_data="back_root")
    builder.adjust(1)
    
    status = (
        f"⚙️ **Текущие настройки рулетки:**\n\n"
        f"• **Триггер:** `{cfg.r_trigger}`\n"
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

# Хэндлеры изменения настроек
@router.callback_query(F.data == "edit_r_start")
async def edit_r_start(callback: CallbackQuery, state: FSMContext):
    await state.set_state(ConfigStates.edit_start)
    await callback.message.edit_text("Отправьте новый HTML текст стартового сообщения. Используйте `{trigger}`:")

@router.message(ConfigStates.edit_start)
async def save_start_msg(message: Message, state: FSMContext):
    async with async_session() as s:
        await s.execute(update(BotConfig).where(BotConfig.id == 1).values(r_start_msg=message.html_text or message.text))
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
    async with async_session() as s:
        await s.execute(update(BotConfig).where(BotConfig.id == 1).values(r_stop_msg=message.html_text or message.text))
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
    async with async_session() as s:
        await s.execute(update(BotConfig).where(BotConfig.id == 1).values(r_winner_template=message.html_text or message.text))
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

# --- УПРАВЛЕНИЕ И ОТМЕНА РОЗЫГРЫШЕЙ ---
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
    await callback.message.edit_text("Выберите розыгрыш, который хотите досрочно закрыть/удалить:", reply_markup=builder.as_markup())

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

# --- СОЗДАНИЕ GIVEAWAY (УЛУЧШЕННОЕ МЕДИА) ---
@router.callback_query(F.data == "cfg_giveaway")
async def start_giveaway_fsm(callback: CallbackQuery, state: FSMContext):
    await state.set_state(GiveawayCreate.text)
    await callback.message.edit_text("🎫 **Создание Розыгрыша.**\nОтправьте текст или полноценный пост (можно прикрепить ОДНО фото/видео):")

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
    await state.set_state(GiveawayCreate.channels)
    await message.answer("Перечислите юзернеймы каналов для Обязательной подписки через запятую (например: `chan1, chan2`). Если не нужно, пришлите `0`:")

@router.message(GiveawayCreate.channels)
async def process_g_channels(message: Message, state: FSMContext):
    txt = message.text.replace("@", "").strip()
    channels = "" if txt == "0" else ",".join([c.strip() for c in txt.split(",")])
    await state.update_data(channels=channels)
    await state.set_state(GiveawayCreate.task)
    await message.answer("Укажите ссылку на кастомное задание (например, реф-ссылка сайта). Если задания нет, пришлите `0`:")

@router.message(GiveawayCreate.task)
async def process_g_task(message: Message, state: FSMContext):
    txt = message.text.strip()
    task = None if txt == "0" else txt
    await state.update_data(task=task)
    
    builder = InlineKeyboardBuilder()
    builder.button(text="⏱ По времени записи", callback_data="g_type_time")
    builder.button(text="👥 По количеству людей", callback_data="g_type_users")
    await message.answer("Выберите тип завершения:", reply_markup=builder.as_markup())

@router.callback_query(F.data.startswith("g_type_"))
async def process_g_type(callback: CallbackQuery, state: FSMContext):
    g_type = callback.data.split("_")[2]
    await state.update_data(end_type=g_type)
    await state.set_state(GiveawayCreate.end_val)
    if g_type == "time":
        await callback.message.edit_text("Укажите время стопа записи в формате ЧЧ:ММ (по Новосибирску):")
    else:
        await callback.message.edit_text("Сколько участников должно набраться для автоматического подведения итогов?")

@router.message(GiveawayCreate.end_val)
async def process_g_val(message: Message, state: FSMContext):
    await state.update_data(end_value=message.text.strip())
    await state.set_state(GiveawayCreate.winners)
    await message.answer("Укажите число победителей:")

@router.message(GiveawayCreate.winners)
async def process_g_winners(message: Message, state: FSMContext):
    try:
        winners_count = int(message.text.strip())
    except:
        await message.answer("Введите число!")
        return
    await state.update_data(winners=winners_count)
    await state.set_state(GiveawayCreate.target_chat)
    await message.answer("Отправьте ID группы/канала (числовой с минусом), куда опубликовать пост:")

@router.message(GiveawayCreate.target_chat)
async def process_g_finalize(message: Message, state: FSMContext, bot: Bot):
    data = await state.get_data()
    try:
        chat_id = int(message.text.strip())
    except:
        await message.answer("Неверный формат ID чата.")
        return
    
    # Получаем юзернейм текущего бота для диплинка
    bot_info = await bot.get_me()
    
    async with async_session() as s:
        # Сначала сохраняем запись в БД, чтобы получить уникальный ID розыгрыша
        new_post = GiveawayPost(
            chat_id=chat_id,
            message_id=0,
            text_data=data['text'],
            media_file_id=data['media_id'],
            channels_to_check=data['channels'],
            task_url=data['task'],
            end_type=data['end_type'],
            end_value=data['end_value'],
            winners_count=data['winners'],
            is_active=True
        )
        s.add(new_post)
        await s.flush()
        g_id = new_post.id
        
        # Кнопка ведет в ЛС бота по диплинку
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🟢 Участвовать (0)", url=f"https://t.me/{bot_info.username}?start=g_{g_id}")]
        ])
        
        sent_msg = None
        if data['media_id']:
            if data['media_type'] == "photo":
                sent_msg = await bot.send_photo(chat_id, photo=data['media_id'], caption=data['text'], reply_markup=kb, parse_mode="HTML")
            elif data['media_type'] == "video":
                sent_msg = await bot.send_video(chat_id, video=data['media_id'], caption=data['text'], reply_markup=kb, parse_mode="HTML")
        else:
            sent_msg = await bot.send_message(chat_id, text=data['text'], reply_markup=kb, parse_mode="HTML")
            
        new_post.message_id = sent_msg.message_id
        await s.commit()
        
    await state.clear()
    await message.answer("🚀 Пост розыгрыша успешно опубликован!")
    await send_main_panel(message)

# --- БЛОК ОГРАНИЧЕНИЙ ---
@router.callback_query(F.data == "cfg_cooldown")
async def cfg_cooldown(callback: CallbackQuery, state: FSMContext):
    await state.set_state(ConfigStates.add_cooldown)
    await callback.message.edit_text("Введите юзернейм игрока и количество дней бана через пробел:\nПример: `UserVasya 7`")

@router.message(ConfigStates.add_cooldown)
async def save_cooldown(message: Message, state: FSMContext):
    try:
        username, days = message.text.split()
        username = username.lstrip("@").strip()
        days_int = int(days)
    except:
        await message.answer("❌ Ошибка ввода. Формат: `ИмяПользователя ЧислоДней`")
        return
        
    until = datetime.datetime.now(tz_nsk) + datetime.timedelta(days=days_int)
    async with async_session() as s:
        await s.merge(WinnerCooldown(username=username, until_date=until.replace(tzinfo=None)))
        await s.commit()
        
    await state.clear()
    await message.answer(f"✅ Игрок @{username} заблокирован на {days_int} дней.")
    await send_main_panel(message)
