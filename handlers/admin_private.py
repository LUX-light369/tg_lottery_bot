# Полный функционал админ-панели с поддержкой FSM состояний
from aiogram import Router, F, Bot
from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder
from aiogram.filters import CommandStart, Command
from aiogram.fsm.context import FSMContext
from config import ADMIN_ID
from states import LotterySetup
import datetime
import zoneinfo
from config import DEFAULT_TZ
from handlers.roulette import start_custom_roulette

router = Router()
tz_nsk = zoneinfo.ZoneInfo(DEFAULT_TZ)

# Временное хранилище глобальных ограничений
GLOBAL_LIMITS = {"max_wins_per_user": 3, "blacklist": []}

@router.message(CommandStart(), F.chat.type == "private")
async def admin_start(message: Message, state: FSMContext):
    if message.from_user.id != ADMIN_ID:
        await message.answer("❌ Доступ заблокирован. Вы не являетесь главным администратором бота.")
        return
    await state.clear()
    
    builder = InlineKeyboardBuilder()
    builder.button(text="🎁 Создать розыгрыш", callback_data="create_lottery")
    builder.button(text="⚙️ Ограничения победителей", callback_data="view_limits")
    builder.adjust(1)

    await message.answer("👋 Панель управления розыгрышами и рулеткой.\nВыберите действие:", reply_markup=builder.as_markup())

@router.callback_query(F.data == "back_main")
async def back_to_main(callback: CallbackQuery, state: FSMContext):
    await state.clear()
    builder = InlineKeyboardBuilder()
    builder.button(text="🎁 Создать розыгрыш", callback_data="create_lottery")
    builder.button(text="⚙️ Ограничения победителей", callback_data="view_limits")
    builder.adjust(1)
    await callback.message.edit_text("👋 Панель управления розыгрышами и рулеткой.\nВыберите действие:", reply_markup=builder.as_markup())

# --- БЛОК ОГРАНИЧЕНИЙ ---
@router.callback_query(F.data == "view_limits")
async def view_limits_handler(callback: CallbackQuery):
    builder = InlineKeyboardBuilder()
    builder.button(text="🔄 Изменить лимит побед", callback_data="change_win_limit")
    builder.button(text="🔙 Назад", callback_data="back_main")
    builder.adjust(1)
    
    msg = (
        f"⚙️ **Текущие настройки ограничений:**\n\n"
        f"• Макс. побед на одного юзера: `{GLOBAL_LIMITS['max_wins_per_user']}`\n"
        f"• Юзеров в черном списке: `{len(GLOBAL_LIMITS['blacklist'])}`"
    )
    await callback.message.edit_text(msg, reply_markup=builder.as_markup(), parse_mode="Markdown")

@router.callback_query(F.data == "change_win_limit")
async def change_win_limit(callback: CallbackQuery):
    builder = InlineKeyboardBuilder()
    builder.button(text="1", callback_data="set_lim_1")
    builder.button(text="2", callback_data="set_lim_2")
    builder.button(text="3", callback_data="set_lim_3")
    builder.button(text="5", callback_data="set_lim_5")
    builder.button(text="🔙 Назад", callback_data="view_limits")
    builder.adjust(4, 1)
    await callback.message.edit_text("Выберите максимальное число побед для одного игрока:", reply_markup=builder.as_markup())

@router.callback_query(F.data.startswith("set_lim_"))
async def save_win_limit(callback: CallbackQuery):
    lim = int(callback.data.split("_")[2])
    GLOBAL_LIMITS["max_wins_per_user"] = lim
    await callback.answer(f"Лимит побед успешно изменен на {lim}!", show_alert=True)
    await view_limits_handler(callback)

# --- БЛОК СОЗДАНИЯ РОЗЫГРЫША (FSM) ---
@router.callback_query(F.data == "create_lottery")
async def setup_lottery(callback: CallbackQuery, state: FSMContext):
    builder = InlineKeyboardBuilder()
    builder.button(text="⏱ По времени (в минутах)", callback_data="mode_time")
    builder.button(text="👥 По кол-ву участников", callback_data="mode_users")
    builder.button(text="🔙 Назад", callback_data="back_main")
    builder.adjust(1)
    await callback.message.edit_text("⚙️ **Шаг 1:** Выберите режим завершения розыгрыша:", reply_markup=builder.as_markup())

@router.callback_query(F.data.in_({"mode_time", "mode_users"}))
async def choose_mode(callback: CallbackQuery, state: FSMContext):
    mode = "time" if callback.data == "mode_time" else "users"
    await state.update_data(mode=mode)
    
    await state.set_state(LotterySetup.entering_limit)
    if mode == "time":
        await callback.message.edit_text("⏱ **Шаг 2:** Введите длительность розыгрыша **в минутах** (например, `5` или `60`):")
    else:
        await callback.message.edit_text("👥 **Шаг 2:** Введите число участников, при достижении которого запись закроется (например, `50`):")

@router.message(LotterySetup.entering_limit, F.chat.type == "private")
async def process_limit(message: Message, state: FSMContext):
    if not message.text.isdigit() or int(message.text) <= 0:
        await message.answer("❌ Пожалуйста, введите корректное число больше нуля!")
        return
    
    await state.update_data(limit_val=int(message.text))
    await state.set_state(LotterySetup.entering_winners)
    await message.answer("🏆 **Шаг 3:** Введите количество призовых мест / победителей (например, `3`):")

@router.message(LotterySetup.entering_winners, F.chat.type == "private")
async def process_winners(message: Message, state: FSMContext):
    if not message.text.isdigit() or int(message.text) <= 0:
        await message.answer("❌ Введите число призовых мест больше нуля!")
        return
        
    await state.update_data(winners_count=int(message.text))
    
    builder = InlineKeyboardBuilder()
    builder.button(text="⏩ Пропустить (Без подписки)", callback_data="skip_link")
    builder.adjust(1)
    
    await state.set_state(LotterySetup.entering_link)
    await message.answer("🔗 **Шаг 4:** Отправьте реферальную ссылку на канал или задание для обязательной подписки игроков (или нажмите кнопку ниже):", reply_markup=builder.as_markup())

@router.callback_query(F.data == "skip_link", LotterySetup.entering_link)
async def skip_link_callback(callback: CallbackQuery, state: FSMContext):
    await state.update_data(link=None)
    await state.set_state(LotterySetup.entering_chat_id)
    await callback.message.edit_text("🆔 **Шаг 5:** Отправьте числовой ID группы/чата, куда бот должен отправить этот розыгрыш (например, `-100123456789`):")

@router.message(LotterySetup.entering_link, F.chat.type == "private")
async def process_link(message: Message, state: FSMContext):
    text = message.text.strip()
    if not text.startswith("http://") and not text.startswith("https://") and not text.startswith("t.me/"):
        await message.answer("❌ Это не похоже на ссылку! Отправьте корректный URL или нажмите кнопку Пропустить.")
        return
        
    await state.update_data(link=text)
    await state.set_state(LotterySetup.entering_chat_id)
    await message.answer("🆔 **Шаг 5:** Отправьте числовой ID группы/чата, куда бот должен отправить этот розыгрыш (например, `-100123456789`):")

@router.message(LotterySetup.entering_chat_id, F.chat.type == "private")
async def process_chat_id(message: Message, state: FSMContext, bot: Bot):
    chat_text = message.text.strip()
    try:
        chat_id = int(chat_text)
    except ValueError:
        await message.answer("❌ ID чата должен состоять из цифр и начинаться с минуса (для супергрупп), например `-100123456789`")
        return

    # Проверяем, есть ли бот в этом чате
    try:
        chat_member = await bot.get_chat_member(chat_id, bot.id)
    except Exception:
        await message.answer("❌ Бот не добавлен в этот чат или указан неверный ID! Сначала добавьте бота в чат администратором.")
        return

    data = await state.get_data()
    
    # Запускаем кастомный розыгрыш в целевом чате
    success = await start_custom_roulette(
        bot=bot,
        chat_id=chat_id,
        mode=data['mode'],
        limit_val=data['limit_val'],
        winners_count=data['winners_count'],
        link=data.get('link')
    )
    
    if success:
        await message.answer(f"🚀 **Розыгрыш успешно запущен в чате {chat_id}!**")
    else:
        await message.answer("❌ Не удалось запустить розыгрыш. Возможно, в чате уже идет активная рулетка.")
        
    await state.clear()
