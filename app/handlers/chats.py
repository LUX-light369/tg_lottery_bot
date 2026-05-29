from aiogram import Router
from aiogram.types import Message

router = Router()


@router.message(lambda m: m.text == "💬 Каналы и чаты")
async def chats(message: Message):
    await message.answer(
        "Отправьте ID канала или чата."
    )
