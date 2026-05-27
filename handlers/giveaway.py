import re
from aiogram import Router, F, Bot
from aiogram.filters import CommandObject, Command
from aiogram.types import Message, CallbackQuery, InlineKeyboardMarkup, InlineKeyboardButton
from database import async_session, GiveawayPost, GiveawayParticipant
from sqlalchemy import select, func

router = Router()

# Обработка перехода по кнопке "Участвовать" из канала в ЛС к боту
@router.message(F.chat.type == "private", Command("start"), F.text.regexp(r"\/start g_(\d+)"))
async def handle_giveaway_start(message: Message, command: CommandObject, bot: Bot):
    g_id = int(command.args.split("_")[1])
    user = message.from_user

    async with async_session() as s:
        post = (await s.execute(select(GiveawayPost).where(GiveawayPost.id == g_id, GiveawayPost.is_active == True))).scalar_one_or_none()
        if not post:
            await message.answer("❌ Этот розыгрыш уже завершен или не существует.")
            return
            
        already_in = (await s.execute(select(GiveawayParticipant).where(GiveawayParticipant.giveaway_id == g_id, GiveawayParticipant.user_id == user.id))).scalar_one_or_none()

    if already_in:
        await message.answer("🎉 Вы уже успешно зарегистрированы в этом розыгрыше!")
        return

    # 1. Проверка обязательных подписок на каналы
    if post.channels_to_check:
        for channel in post.channels_to_check.split(","):
            ch_name = channel.strip().replace("@", "")
            if not ch_name: continue
            try:
                member = await bot.get_chat_member(chat_id=f"@{ch_name}", user_id=user.id)
                if member.status in {"left", "kicked"}:
                    # Кнопка проверки прямо в ЛС
                    kb = InlineKeyboardMarkup(inline_keyboard=[
                        [InlineKeyboardButton(text=f"📢 Подписаться на @{ch_name}", url=f"https://t.me/{ch_name}")],
                        [InlineKeyboardButton(text="🔄 Проверить подписку и участие", url=f"https://t.me/{(await bot.get_me()).username}?start=g_{g_id}")]
                    ])
                    await message.answer(f"❌ Для участия необходимо подписаться на канал @{ch_name}!", reply_markup=kb)
                    return
            except Exception:
                pass 

    # 2. Проверка кастомного задания (если оно есть)
    # Если у поста есть задание, а юзер пришел по обычной ссылке — предлагаем выполнить задание
    if post.task_url and not message.text.endswith("_done"):
        kb = InlineKeyboardMarkup(inline_keyboard=[
            [InlineKeyboardButton(text="🔗 Выполнить задание", url=post.task_url)],
            [InlineKeyboardButton(text="✅ Я выполнил, зарегистрироваться", url=f"https://t.me/{(await bot.get_me()).username}?start=g_{g_id}_done")]
        ])
        await message.answer("📝 Для участия в розыгрыше выполните задание спонсора, после чего нажмите кнопку ниже:", reply_markup=kb)
        return

    # 3. Успешная регистрация
    async with async_session() as s:
        s.add(GiveawayParticipant(
            giveaway_id=post.id, 
            user_id=user.id, 
            username=user.username or user.first_name
        ))
        await s.commit()
        
        # Получаем обновленный счетчик участников
        count = (await s.execute(select(func.count(GiveawayParticipant.id)).where(GiveawayParticipant.giveaway_id == post.id))).scalar()

    # Обновляем зеленую кнопку в исходном канале/чате
    bot_info = await bot.get_me()
    kb_channel = InlineKeyboardMarkup(inline_keyboard=[
        [InlineKeyboardButton(text=f"🟢 Участвовать ({count})", url=f"https://t.me/{bot_info.username}?start=g_{post.id}")]
    ])
    
    try: 
        await bot.edit_message_reply_markup(chat_id=post.chat_id, message_id=post.message_id, reply_markup=kb_channel)
    except Exception: 
        pass
        
    await message.answer("🎉 Поздравляем! Вы успешно зарегистрировались в розыгрыше. Ожидайте подведения итогов!")
