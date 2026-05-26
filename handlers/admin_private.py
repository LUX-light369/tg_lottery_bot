import asyncio
from aiogram import Router, F
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from aiogram.filters import CommandStart

router = Router()

@router.message(CommandStart(), F.chat.type == "private")
async def admin_start(message: Message):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🎁 Создать розыгрыш", callback_query_data="create_lottery")],
        [InlineKeyboardButton(text="⚙️ Ограничения победителей", callback_query_data="view_limits")]
    ])
    await message.answer("Добро пожаловать в панель управления розыгрышами!", reply_markup=keyboard)

@router.callback_query(F.data == "create_lottery")
async def setup_lottery(callback: CallbackQuery):
    keyboard = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text="🔗 Задать реф. ссылку + Задание", callback_query_data="set_task")],
        [InlineKeyboardButton(text="⏱ Режим: По времени", callback_query_data="mode_time")],
        [InlineKeyboardButton(text="👥 Режим: По кол-ву участников", callback_query_data="mode_users")],
        [InlineKeyboardButton(text="🔙 Назад", callback_query_data="back_main")]
    ])
    await callback.message.edit_text("⚙️ **Настройка нового розыгрыша:**\nВыберите параметры ниже:", reply_markup=keyboard)

@router.callback_query(F.data == "set_task")
async def set_task_simulation(callback: CallbackQuery):
    # Демонстрация симуляции проверки задания со стороны бота для пользователя
    await callback.answer("Ссылка успешно привязана к кнопке проверки выполнения!", show_alert=True)

# Интерактивный пример имитации проверки для участника (запускается при клике на пост розыгрыша)
async def simulate_user_check_task(callback_query: CallbackQuery):
    """Имитация проверки выполнения реферального задания для участника"""
    await callback_query.answer()
    
    # Плавное обновление статуса (эффект «живой» проверки)
    status_msg = await callback_query.message.answer("⏳ [Проверка выполнения задания... 0%]")
    await asyncio.sleep(1.5)
    await status_msg.edit_text("⏳ [Проверяем переход по реферальной ссылке... 45%]")
    await asyncio.sleep(2.0)
    await status_msg.edit_text("⏳ [Анализируем активацию бота... 85%]")
    await asyncio.sleep(1.2)
    
    await status_msg.edit_text("✅ **Условие успешно выполнено!** Вы внесены в список участников розыгрыша.")
