# Принудительный сброс кэша Bothost v3
import asyncio
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.filters import CommandStart
from config import ADMIN_ID

router = Router()

@router.message(CommandStart(), F.chat.type == "private")
async def admin_start(message: Message):
    # Строгая проверка на админа
    if message.from_user.id != ADMIN_ID:
        await message.answer("❌ Доступ заблокирован. Вы не являетесь главным администратором бота.")
        return

    # Создаем клавиатуру через билдер
    builder = InlineKeyboardBuilder()
    builder.button(text="🎁 Создать розыгрыш", callback_data="create_lottery")
    builder.button(text="⚙️ Ограничения победителей", callback_data="view_limits")
    # Располагаем кнопки друг под другом (в 1 колонку)
    builder.adjust(1)

    await message.answer(
        "👋 Добро пожаловать в панель управления розыгрышами!", 
        reply_markup=builder.as_markup()
    )

@router.callback_query(F.data == "create_lottery")
async def setup_lottery(callback: CallbackQuery):
    if callback.from_user.id != ADMIN_ID:
        await callback.answer("Отказано в доступе", show_alert=True)
        return
        
    builder = InlineKeyboardBuilder()
    builder.button(text="🔗 Задать реф. ссылку + Задание", callback_data="set_task")
    builder.button(text="⏱ Режим: По времени", callback_data="mode_time")
    builder.button(text="👥 Режим: По кол-ву участников", callback_data="mode_users")
    builder.button(text="🔙 Назад", callback_data="back_main")
    builder.adjust(1)

    await callback.message.edit_text(
        "⚙️ **Настройка нового розыгрыша:**\nВыберите параметры ниже:", 
        reply_markup=builder.as_markup()
    )

@router.callback_query(F.data == "set_task")
async def set_task_simulation(callback: CallbackQuery):
    await callback.answer("Ссылка успешно привязана к кнопке проверки выполнения!", show_alert=True)

@router.callback_query(F.data == "back_main")
async def back_to_main(callback: CallbackQuery):
    builder = InlineKeyboardBuilder()
    builder.button(text="🎁 Создать розыгрыш", callback_data="create_lottery")
    builder.button(text="⚙️ Ограничения победителей", callback_data="view_limits")
    builder.adjust(1)
    
    await callback.message.edit_text(
        "👋 Добро пожаловать в панель управления розыгрышами!", 
        reply_markup=builder.as_markup()
    )

@router.callback_query(F.data == "view_limits")
async def view_limits_handler(callback: CallbackQuery):
    builder = InlineKeyboardBuilder()
    builder.button(text="🔙 Назад", callback_data="back_main")
    
    await callback.message.edit_text(
        "📋 Список ограничений пуст. Новые победители пока не зафиксированы.", 
        reply_markup=builder.as_markup()
    )
