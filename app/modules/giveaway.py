import json
import uuid

from aiogram import Router
from aiogram.types import Message, CallbackQuery
from aiogram.utils.keyboard import InlineKeyboardBuilder

from app.database.db import db

router = Router()


def join_keyboard(giveaway_uuid: str, count: int):
    builder = InlineKeyboardBuilder()

    builder.button(
        text=f"🎉 Участвовать ({count})",
        callback_data=f"join:{giveaway_uuid}"
    )

    return builder.as_markup()


@router.message(lambda m: m.text == "🎁 Создать розыгрыш")
async def create_giveaway(message: Message):

    giveaway_uuid = str(uuid.uuid4())[:8]

    prizes = ["Приз"]

    async with await db.connect() as conn:

        await conn.execute(
            '''
            INSERT INTO giveaways (
                giveaway_uuid,
                title,
                post_chat_id,
                winners_count,
                prizes,
                status
            )
            VALUES (?, ?, ?, ?, ?, ?)
            ''',
            (
                giveaway_uuid,
                "Тестовый розыгрыш",
                message.chat.id,
                1,
                json.dumps(prizes),
                "active"
            )
        )

        await conn.commit()

    await message.answer(
        "🎁 Тестовый розыгрыш создан.",
        reply_markup=join_keyboard(giveaway_uuid, 0)
    )


@router.callback_query(lambda c: c.data.startswith("join:"))
async def join(callback: CallbackQuery):

    giveaway_uuid = callback.data.split(":")[1]

    async with await db.connect() as conn:

        cursor = await conn.execute(
            '''
            SELECT id, participants_count
            FROM giveaways
            WHERE giveaway_uuid = ?
            ''',
            (giveaway_uuid,)
        )

        giveaway = await cursor.fetchone()

        if not giveaway:
            await callback.answer("Розыгрыш не найден.")
            return

        await conn.execute(
            '''
            INSERT INTO giveaway_participants (
                giveaway_id,
                user_id,
                username
            )
            VALUES (?, ?, ?)
            ''',
            (
                giveaway[0],
                callback.from_user.id,
                callback.from_user.username
            )
        )

        await conn.execute(
            '''
            UPDATE giveaways
            SET participants_count = participants_count + 1
            WHERE id = ?
            ''',
            (giveaway[0],)
        )

        await conn.commit()

    await callback.message.edit_reply_markup(
        reply_markup=join_keyboard(
            giveaway_uuid,
            giveaway[1] + 1
        )
    )

    await callback.answer(
        "✅ Вы участвуете."
    )
