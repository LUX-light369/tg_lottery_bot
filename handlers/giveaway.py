from aiogram import Router, F, Bot
from aiogram.types import CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from database import async_session, GiveawayPost, GiveawayParticipant, select, update
from sqlalchemy import func

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

    # 1. Проверка обязательных подписок на каналы
    if post.channels_to_check:
        for channel in post.channels_to_check.split(","):
            try:
                member = await bot.get_chat_member(chat_id=f"@{channel.strip()}", user_id=user.id)
                if member.status in {"left", "kicked"}:
                    await callback.answer(f"❌ Вы не подписаны на спонсорский канал @{channel.strip()}!", show_alert=True)
                    return
            except Exception:
                pass # Если бот не админ в каком-то канале, пропускаем проверку

    # 2. Имитация выполнения реф. ссылки / кастомного задания
    if post.task_url and not callback.message.reply_markup.inline_keyboard[0][0].text.startswith("✅"):
        # Если есть урл задания и юзер кликает первый раз — отправляем выполнять задание
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔗 Выполнить задание", url=post.task_url)],
            [InlineKeyboardButton(text="✅ Проверить выполнение", callback_data="g_join_active")]
        ])
        await callback.answer("Выполните кастомное задание по ссылке, затем нажмите Проверить!", show_alert=True)
        try: await callback.message.edit_reply_markup(reply_markup=kb)
        except: pass
        return

    if already_in:
        await callback.answer("Вы уже успешно зарегистрированы в розыгрыше! 🎉", show_alert=True)
        return

    # Записываем участника
    async with async_session() as s:
        s.add(GiveawayParticipant(giveaway_id=post.id, user_id=user.id, username=user.username or user.first_name))
        await s.commit()
        
        # Обновляем счетчик на кнопке
        count = (await s.execute(select(func.count(GiveawayParticipant.id)).where(GiveawayParticipant.giveaway_id == post.id))).scalar()

    # Возвращаем стандартную зеленую кнопку с новым счетчиком
    kb = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"🟢 Участвовать ({count})", callback_data="g_join_active")]
    ])
    try: await callback.message.edit_reply_markup(reply_markup=kb)
    except: pass
    await callback.answer("🎉 Успех! Вы стали участником розыгрыша.", show_alert=True)
