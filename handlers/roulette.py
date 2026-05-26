import datetime
import re
import zoneinfo
import os
from aiogram import Bot, Router, F
from aiogram.types import Message, ChatPermissions
from aiogram.filters import Command
from database import async_session, RouletteSession, RouletteParticipant, UserBan
from sqlalchemy import select, update, delete
from utils.crypto import generate_provably_fair_round, get_fair_winners
from utils.image_gen import generate_gta_results
from scheduler import scheduler
from config import DEFAULT_TZ

router = Router()

def mask_username(username: str) -> str:
    """Маскирование по правилу: убрать @, первые 2 символа закрыть *"""
    uname = username.lstrip('@')
    if len(uname) <= 2:
        return "**"
    return "**" + uname[2:]

async def stop_roulette_action(bot: Bot, chat_id: int):
    """Триггер окончания записи, вызываемый планировщиком"""
    async with async_session() as session:
        res = await session.execute(select(RouletteSession).where(RouletteSession.chat_id == chat_id))
        session_data = res.scalar_one_or_none()
        if not session_data or not session_data.is_active:
            return

        # Извлекаем участников в хронологическом порядке добавления
        p_res = await session.execute(
            select(RouletteParticipant)
            .where(RouletteParticipant.chat_id == chat_id)
            .order_by(RouletteParticipant.id.asc())
        )
        all_parts = p_res.scalars().all()

    # Фильтруем валидных участников
    valid_participants = [p for p in all_parts if not p.is_disqualified]
    
    # 1. Стоп-сообщение в чат
    await bot.send_message(chat_id, "🛑 СТОП ЗАПИСЬ! Сбор участников завершен. Анализируем данные...")

    # Формируем списки
    full_admin_list = []
    masked_chat_list = []
    for idx, p in enumerate(valid_participants, start=1):
        full_admin_list.append(f"{idx}. @{p.username} (ID: {p.user_id})")
        masked_chat_list.append(f"{idx}. {mask_username(p.username)}")

    # Отправляем маскированный список в чат
    chat_list_msg = "📋 **Список участников:**\n" + ("\n".join(masked_chat_list) if masked_chat_list else "Участников нет.")
    await bot.send_message(chat_id, chat_list_msg, parse_mode="Markdown")

    # Получаем ID админа (кто запустил), отправим ему полный список. 
    # В реальном масштабе можно хранить admin_id в RouletteSession. Для примера отправляем в лог или дефолтному чату.
    
    if session_data.only_list_mode:
        await bot.send_message(chat_id, "🎲 Розыгрыш проводится админом вручную через сторонний рандомайзер под видео!")
        # Закрываем игровую сессию
        async with async_session() as s:
            await s.execute(delete(RouletteParticipant).where(RouletteParticipant.chat_id == chat_id))
            await s.execute(update(RouletteSession).where(RouletteSession.chat_id == chat_id).values(is_active=False))
            await s.commit()
        return

    # Вычисляем победителей через Provably Fair
    winners = get_fair_winners(valid_participants, session_data.winners_count, session_data.seed, session_data.salt)
    
    # Ищем их порядковые номера в исходном валидном списке
    winner_indices = []
    winner_mentions = []
    for w in winners:
        idx = valid_participants.index(w) + 1
        winner_indices.append(idx)
        winner_mentions.append(f"#{idx} @{w.username}")

    # Генерация времени
    tz = zoneinfo.ZoneInfo(DEFAULT_TZ)
    now_nsk = datetime.datetime.now(tz).strftime("%d.%m.%Y %H:%M:%S")

    # Генерация картинки GTA
    img_path = generate_gta_results(winner_indices, len(valid_participants), now_nsk)

    # Публикация картинки с подписью результатов
    caption = (
        f"🏆 **РЕЗУЛЬТАТЫ РУЛЕТКИ** 🏆\n\n"
        f"Поздравляем победителей:\n" + "\n".join(winner_mentions) + "\n\n"
        f"🔐 **Проверка честности (Provably Fair):**\n"
        f"Seed: `{session_data.seed}`\n"
        f"Salt: `{session_data.salt}`\n"
        f"SHA-256 хэш раунда (был известен до старта): \n`{session_data.sha_hash}`\n\n"
        f"Вы можете проверить хэш, соединив `Seed:Salt` в любом SHA256 калькуляторе!"
    )

    if os.path.exists(img_path):
        from aiogram.types import FSInputFile
        await bot.send_photo(chat_id, photo=FSInputFile(img_path), caption=caption, parse_mode="Markdown")
        try:
            os.remove(img_path)
        except:
            pass
    else:
        await bot.send_message(chat_id, caption, parse_mode="Markdown")

    # Снятие мутов с нарушителей по завершении рулетки
    for p in all_parts:
        if p.is_disqualified:
            try:
                await bot.restrict_chat_member(
                    chat_id=chat_id,
                    user_id=p.user_id,
                    permissions=ChatPermissions(
                        can_send_messages=True,
                        can_send_audios=True,
                        can_send_documents=True,
                        can_send_photos=True,
                        can_send_videos=True,
                        can_send_video_notes=True,
                        can_send_voice_notes=True,
                        can_send_polls=True,
                        can_send_other_messages=True,
                        can_add_web_page_previews=True
                    )
                )
            except Exception:
                pass

    # Очистка сессии из БД
    async with async_session() as s:
        await s.execute(delete(RouletteParticipant).where(RouletteParticipant.chat_id == chat_id))
        await s.execute(update(RouletteSession).where(RouletteSession.chat_id == chat_id).values(is_active=False))
        await s.commit()

@router.message(Command("рулетка"))
@router.message(F.text.startswith("@рулетка"))
async def start_roulette_cmd(message: Message, bot: Bot):
    # Проверка на админа в группе
    member = await bot.get_chat_member(message.chat.id, message.from_user.id)
    if member.status not in ["administrator", "creator"]:
        return # Игнорируем не-админов

    text = message.text.replace("@рулетка", "").strip()
    
    # Регулярные выражения парсинга параметров команд
    # Форматы: "3п 20:00", "3п", "19:00"
    p_match = re.search(r'(\d+)п', text)
    t_match = re.search(r'(\d{2}:\d{2})', text)

    winners_count = int(p_match.group(1)) if p_match else 1
    time_str = t_match.group(1) if t_match else None
    only_list_mode = False if p_match else True # Если указали только время без "п", значит ручной режим рандома

    # Логика планирования старта
    delay_minutes = 5 # Сбор участников длится 5 минут по умолчанию
    
    # Инициализация параметров честности Provably Fair
    seed, salt, sha_hash = generate_provably_fair_round()

    async with async_session() as session:
        # Создаем или обновляем запись параметров рулетки для чата
        stop_time = datetime.datetime.now() + datetime.timedelta(minutes=delay_minutes)
        
        await session.merge(RouletteSession(
            chat_id=message.chat.id,
            is_active=True,
            trigger_symbol="+",
            winners_count=winners_count,
            stop_time=stop_time,
            seed=seed,
            salt=salt,
            sha_hash=sha_hash,
            only_list_mode=only_list_mode
        ))
        await session.commit()

    # Сообщение о начале
    start_msg = (
        f"🎰 **СТАРТ РУЛЕТКИ!** 🎰\n\n"
        f"Отправьте ровно один символ `+` для участия!\n"
        f"⏱ Запись закроется через {delay_minutes} мин.\n"
        f"Количество победителей: {'Вручную админом' if only_list_mode else winners_count}\n\n"
        f"🔐 **Хэш честности раунда (SHA-256):** \n`{sha_hash}`"
    )
    await message.answer(start_msg, parse_mode="Markdown")

    # Планируем автоматический стоп
    scheduler.add_job(
        stop_roulette_action,
        'date',
        run_date=stop_time,
        args=[bot, message.chat.id],
        id=f"roulette_{message.chat.id}",
        replace_existing=True
    )

@router.message(F.chat.type.in_({"group", "supergroup"}))
async def handle_chat_messages(message: Message, bot: Bot):
    """Слушатель игрового чата во время активной рулетки"""
    if not message.text:
        return

    async with async_session() as session:
        res = await session.execute(select(RouletteSession).where(RouletteSession.chat_id == message.chat.id))
        session_data = res.scalar_one_or_none()
        
        if not session_data or not session_data.is_active:
            return

        user = message.from_user
        text_clean = message.text.strip()

        # Поиск игрока в текущей сессии
        p_res = await session.execute(
            select(RouletteParticipant)
            .where(RouletteParticipant.chat_id == message.chat.id, RouletteParticipant.user_id == user.id)
        )
        participant = p_res.scalar_one_or_none()

        # Сценарий 1: Пользователь отправляет валидный плюс
        if text_clean == session_data.trigger_symbol:
            # Проверка наличия Юзернейма
            if not user.username:
                await message.reply(
                    "⚠️ Для участия в рулетке вам необходимо установить **username** в настройках профиля Telegram до завершения записи, иначе ваш голос не будет зафиксирован!"
                )
                return

            if participant:
                # Если уже присылал плюс ранее — дисквалификация за дабл-клик
                if not participant.is_disqualified:
                    await session.execute(
                        update(RouletteParticipant)
                        .where(RouletteParticipant.id == participant.id)
                        .values(is_disqualified=True)
                    )
                    await session.commit()
                    await message.answer(f"🚫 Игрок @{user.username} отправил '+' повторно! Дисквалификация и мут до конца раунда.")
                    try:
                        await bot.restrict_chat_member(message.chat.id, user.id, ChatPermissions(can_send_messages=False))
                    except Exception: pass
                await message.delete()
                return
            else:
                # Первая успешная регистрация
                session.add(RouletteParticipant(
                    chat_id=message.chat.id,
                    username=user.username,
                    user_id=user.id,
                    msg_count=0
                ))
                await session.commit()
                return

        # Сценарий 2: Пользователь пишет ЛЮБОЕ сообщение, кроме плюса во время игры
        else:
            await message.delete() # Удаляем лишний флуд немедленно
            
            if participant:
                new_count = participant.msg_count + 1
                if new_count >= 2:
                    # Порог нарушений превышен -> Дисквалификация + Мут
                    await session.execute(
                        update(RouletteParticipant)
                        .where(RouletteParticipant.id == participant.id)
                        .values(msg_count=new_count, is_disqualified=True)
                    )
                    await session.commit()
                    await message.answer(f"🚫 Игрок @{user.username} нарушил правила общения в рулетке! Дисквалификация и мут.")
                    try:
                        await bot.restrict_chat_member(message.chat.id, user.id, ChatPermissions(can_send_messages=False))
                    except Exception: pass
                else:
                    await session.execute(
                        update(RouletteParticipant)
                        .where(RouletteParticipant.id == participant.id)
                        .values(msg_count=new_count)
                    )
                    await session.commit()
