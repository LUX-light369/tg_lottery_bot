import asyncio
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import CommandStart
from config import ADMIN_ID

router = Router()

# Фильтр: обрабатывать сообщения в личке только от главного админа
@router.message(CommandStart(), F.chat.type == "private")
async def admin_start(message: Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("❌ Доступ заблокирован. Вы не являетесь главным администратором бота.")
        return

    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎁 Создать розыгрыш", callback_query_data="create_lottery")],
        [InlineKeyboardButton(text="⚙️ Ограничения победителей", callback_query_data="view_limits")]
    ])
    await message.answer("Добро пожаловать в панель управления розыгрышами!", reply_markup=keyboard)

@router.callback_query(F.data == "create_lottery")
async def setup_lottery(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("Отказано в доступе", show_alert=True)
        return
        
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔗 Задать реф. ссылку + Задание", callback_query_data="set_task")],
        [InlineKeyboardButton(text="⏱ Режим: По времени", callback_query_data="mode_time")],
        [InlineKeyboardButton(text="👥 Режим: По кол-ву участников", callback_query_data="mode_users")],
        [InlineKeyboardButton(text="🔙 Назад", callback_query_data="back_main")]
    ])
    await callback.message.edit_text("⚙️ **Настройка нового розыгрыша:**\nВыберите параметры ниже:", reply_markup=keyboard)

@router.callback_query(F.data == "set_task")
async def set_task_simulation(callback: CallbackQuery):
    await callback.answer("Ссылка успешно привязана к кнопке проверки выполнения!", show_alert=True)

@router.callback_query(F.data == "back_main")
async def back_to_main(callback: CallbackQuery):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎁 Создать розыгрыш", callback_query_data="create_lottery")],
        [InlineKeyboardButton(text="⚙️ Ограничения победителей", callback_query_data="view_limits")]
    ])
    await callback.message.edit_text("Добро пожаловать в панель управления розыгрышами!", reply_markup=keyboard)

@router.callback_query(F.data == "view_limits")
async def view_limits_handler(callback: CallbackQuery):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Назад", callback_query_data="back_main")]
    ])
    await callback.message.edit_text("📋 Список ограничений пуст. Новые победители пока не зафиксированы.", reply_markup=keyboard)
