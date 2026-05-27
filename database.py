import datetime
from sqlalchemy.ext.asyncio import create_async_engine, AsyncSession, async_sessionmaker
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import String, Integer, Boolean, DateTime, Text, BigInteger, select, update, delete

DATABASE_URL = "sqlite+aiosqlite:///./data/roulette_bot.db"

engine = create_async_engine(DATABASE_URL, echo=False)
async_session = async_sessionmaker(engine, expire_on_commit=False, class_=AsyncSession)

class Base(DeclarativeBase):
    pass

class BotConfig(Base):
    __tablename__ = "bot_config"
    id: Mapped[int] = mapped_column(primary_key=True)
    # Настройки Рулетки
    r_start_msg: Mapped[str] = mapped_column(Text, default="🎰 **ЗАПИСЬ НАЧАТА!** Отправь {trigger} для участия!")
    r_stop_msg: Mapped[str] = mapped_column(Text, default="🛑 **СТОП ЗАПИСЬ!** Участники собраны.")
    r_winner_template: Mapped[str] = mapped_column(Text, default="🏆 **НАШИ ПОБЕДИТЕЛИ:**\n{winners}\n\nПризы: {default_prizes}")
    r_default_prizes: Mapped[str] = mapped_column(Text, default="Приз")
    r_trigger: Mapped[str] = mapped_column(String(50), default="+")
    # Лимиты
    max_wins_per_user: Mapped[int] = mapped_column(Integer, default=3)

class RouletteSession(Base):
    __tablename__ = "roulette_sessions"
    chat_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False)
    is_joined_active: Mapped[bool] = mapped_column(Boolean, default=False) # Открыт ли прием плюсов прямо сейчас
    winners_count: Mapped[int] = mapped_column(Integer, default=1)
    seed: Mapped[str] = mapped_column(String(100), nullable=True)
    salt: Mapped[str] = mapped_column(String(100), nullable=True)
    sha_hash: Mapped[str] = mapped_column(String(100), nullable=True)
    prizes: Mapped[str] = mapped_column(Text, default="Приз")
    created_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=datetime.datetime.utcnow)

class RouletteParticipant(Base):
    __tablename__ = "roulette_participants"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    chat_id: Mapped[int] = mapped_column(BigInteger)
    user_id: Mapped[int] = mapped_column(BigInteger)
    username: Mapped[str] = mapped_column(String(200))
    is_disqualified: Mapped[bool] = mapped_column(Boolean, default=False)

class PastRouletteRound(Base):
    __tablename__ = "past_roulette_rounds"
    chat_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    winners_json: Mapped[str] = mapped_column(Text) # Сохраненный список прошлых победителей
    participants_json: Mapped[str] = mapped_column(Text) # Кэш всех участников раунда
    updated_at: Mapped[datetime.datetime] = mapped_column(DateTime, default=datetime.datetime.utcnow)

class GiveawayPost(Base):
    __tablename__ = "giveaway_posts"
    id: Mapped[int] = mapped_column(primary_key=True, autoincrement=True)
    chat_id: Mapped[int] = mapped_
