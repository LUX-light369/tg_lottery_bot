import datetime
from typing import List, Optional
from sqlalchemy.ext.asyncio import AsyncSession, create_async_engine, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import BigInteger, String, Text, Boolean, DateTime, select

# Укажите вашу строку подключения (из конфигурации или переменных окружения)
from config import DATABASE_URL

engine = create_async_engine(DATABASE_URL, echo=False)
async_session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

class Base(DeclarativeBase):
    pass

class BotConfig(Base):
    __tablename__ = "bot_config"
    id: Mapped[int] = mapped_column(primary_key=True)
    r_trigger: Mapped[str] = mapped_column(String(50), default="👍")
    r_default_prizes: Mapped[str] = mapped_column(Text, default="Приз 1, Приз 2, Приз 3")
    r_start_msg: Mapped[str] = mapped_column(Text, default="🎰 Запись на рулетку открыта! Отправьте {trigger} для участия!")
    r_stop_msg: Mapped[str] = mapped_column(Text, default="🛑 Запись на рулетку окончена! Производится расчет...")
    r_winner_template: Mapped[str] = mapped_column(Text, default="🎉 Победители рулетки:\n{winners}")

class RouletteSession(Base):
    __tablename__ = "roulette_sessions"
    chat_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False)
    is_joined_active: Mapped[bool] = mapped_column(Boolean, default=False)
    winners_count: Mapped[int] = mapped_column(default=1)
    seed: Mapped[str] = mapped_column(String(100))
    salt: Mapped[str] = mapped_column(String(100))
    sha_hash: Mapped[str] = mapped_column(String(100))
    prizes: Mapped[str] = mapped_column(Text)

class RouletteParticipant(Base):
    __tablename__ = "roulette_participants"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    chat_id: Mapped[int] = mapped_column(BigInteger)
    user_id: Mapped[int] = mapped_column(BigInteger)
    username: Mapped[str] = mapped_column(String(100))
    is_disqualified: Mapped[bool] = mapped_column(Boolean, default=False)

class PastRouletteRound(Base):
    __tablename__ = "past_roulette_rounds"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    chat_id: Mapped[int] = mapped_column(BigInteger)
    winners_json: Mapped[str] = mapped_column(Text)
    participants_json: Mapped[str] = mapped_column(Text)
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=datetime.datetime.utcnow)

class WinnerCooldown(Base):
    __tablename__ = "winner_cooldowns"
    username: Mapped[str] = mapped_column(String(100), primary_key=True)
    until_date: Mapped[datetime.datetime] = mapped_column(DateTime)

class GiveawayPost(Base):
    __tablename__ = "giveaway_posts"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    chat_id: Mapped[int] = mapped_column(BigInteger)
    message_id: Mapped[int] = mapped_column(BigInteger)
    text_data: Mapped[str] = mapped_column(Text)
    media_file_id: Mapped[Optional[str]] = mapped_column(String(250), nullable=True)
    channels_to_check: Mapped[str] = mapped_column(Text, default="")
    task_url: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    end_type: Mapped[str] = mapped_column(String(50)) # time / users
    end_value: Mapped[str] = mapped_column(String(50))
    winners_count: Mapped[int] = mapped_column(default=1)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)

class GiveawayParticipant(Base):
    __tablename__ = "giveaway_participants"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    giveaway_id: Mapped[int] = mapped_column(BigInteger)
    user_id: Mapped[int] = mapped_column(BigInteger)
    username: Mapped[str] = mapped_column(String(100))

# Новые таблицы быстрого выбора для Администратора
class SavedTargetChat(Base):
    __tablename__ = "saved_target_chats"
    chat_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    title: Mapped[str] = mapped_column(String(200))

class SavedCheckChannel(Base):
    __tablename__ = "saved_check_channels"
    username: Mapped[str] = mapped_column(String(200), primary_key=True)

async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    
    # Первичная инициализация конфигурации
    async with async_session() as session:
        cfg = (await session.execute(select(BotConfig).where(BotConfig.id == 1))).scalar_one_or_none()
        if not cfg:
            session.add(BotConfig(id=1))
            await session.commit()
