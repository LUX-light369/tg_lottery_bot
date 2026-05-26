# Хак сброса кэша сборки Bothost v2
import asyncio
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import CommandStart
from config import ADMIN_ID

router = Router()

@router.message(CommandStart(), F.chat.type == "private")
async def admin_start(message: Message):
    if message.from_user.id != ADMIN_ID:
        await message.answer("❌ Доступ заблокирован. Вы не являетесь главным администратором бота.")
        return

    # Изменили текст здесь, чтобы Docker зафиксировал изменение строки
    await message.answer(
        "👋 Добро пожаловать в обновленную панель управления розыгрышами!", 
        reply_markup=InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🎁 Создать розыгрыш", callback_query_data="create_lottery")],
            [InlineKeyboardButton(text="⚙️ Ограничения победителей", callback_query_data="view_limits")]
        ])
    )

    await callback.message.edit_text("Добро пожаловать в панель управления розыгрышами!", reply_markup=keyboard)

@router.callback_query(F.data == "view_limits")
async def view_limits_handler(callback: CallbackQuery):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔙 Назад", callback_query_data="back_main")]
    ])
    await callback.message.edit_text("📋 Список ограничений пуст. Новые победители пока не зафиксированы.", reply_markup=keyboard)
