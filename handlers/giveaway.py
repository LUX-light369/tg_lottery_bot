from aiogram import Router, F, Bot
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
# ИСПРАВЛЕНО: Чистые импорты моделей из твоей базы данных
from database import async_session, GiveawayPost, GiveawayParticipant
# ИСПРАВЛЕНО: select и func импортируются строго из sqlalchemy
from sqlalchemy import select, func 

router = Router()

@router.callback_query(F.data == "g_join_active")
async def handle_giveaway_join(callback: CallbackQuery, bot: Bot):
    user = callback.from_user
    msg_id = callback.message.message_id
    chat_id = callback.message.chat.id
    
    async with async_session() as s:
        post = (await s.execute(select(GiveawayPost).where(GiveawayPost.chat_id == chat_id, GiveawayPost.message_id == msg_id, GiveawayPost.is_active == True))).scalar_one_or_none()
        if not post:
            await callback.answer("❌ Розыгрыш уже завершен!", show_alert=True)
            return
            
        already_in = (await s.execute(select(GiveawayParticipant).where(GiveawayParticipant.giveaway_id == post.id, GiveawayParticipant.user_id == user.id))).scalar_one_or_none()

    if already_in:
        await callback.answer("Вы уже успешно зарегистрированы в розыгрыше! 🎉", show_alert=True)
        return

    # 1. Проверка обязательных подписок на каналы
    if post.channels_to_check:
        for channel in post.channels_to_check.split(","):
            try:
                member = await bot.get_chat_member(chat_id=f"@{channel.strip()}", user_id=user.id)
                if member.status in {"left", "kicked"}:
                    await callback.answer(f"❌ Вы не подписаны на спонсорский канал @{channel.strip()}!", show_alert=True)
                    return
            except Exception:
                pass # Если бот не админ в каком-то канале, просто пропускаем

    # 2. ИСПРАВЛЕНО: Надежная проверка клика по кнопке "Проверить выполнение"
    # Проверяем, отображается ли сейчас кнопка выполнения задания. Если да — пропускаем к регистрации.
    current_kb = callback.message.reply_markup.inline_keyboard
    has_task_button = any(btn.callback_data == "g_join_active" and "Проверить" in btn.text for row in current_kb for btn in row)

    if post.task_url and not has_task_button:
        # Если задание есть, но пользователь кликнул самый первый раз (кнопки проверки еще нет)
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔗 Выполнить задание", url=post.task_url)],
            [InlineKeyboardButton(text="✅ Проверить выполнение", callback_data="g_join_active")]
        ])
        await callback.answer("Выполните кастомное задание по ссылке, затем нажмите «Проверить выполнение»!", show_alert=True)
        try: 
            await callback.message.edit_reply_markup(reply_markup=kb)
        except Exception: 
            pass
        return

    # 3. Записываем участника в базу данных
    async with async_session() as s:
        s.add(GiveawayParticipant(
            giveaway_id=post.id, 
            user_id=user.id, 
            username=user.username or user.first_name
        ))
        await s.commit()
        
        # Получаем актуальный счетчик участников
        count = (await s.execute(select(func.count(GiveawayParticipant.id)).where(GiveawayParticipant.giveaway_id == post.id))).scalar()

    # Возвращаем стандартную зеленую кнопку с обновленным числом участников
    bot_info = await bot.get_me()
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"🟢 Участвовать ({count})", url=f"https://t.me/{bot_info.username}?start=g_{post.id}")]
    ])
    
    try: 
        await callback.message.edit_reply_markup(reply_markup=kb)
    except Exception: 
        pass
        
    await callback.answer("🎉 Успех! Вы стали участником розыгрыша.", show_alert=True)
