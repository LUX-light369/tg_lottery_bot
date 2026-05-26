import datetime
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker, AsyncSession
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy import String, Integer, DateTime, Boolean, select, delete
from config import DATABASE_URL

engine = create_async_engine(DATABASE_URL, echo=False)
async_session = async_sessionmaker(engine, expire_on_commit=False)

class Base(DeclarativeBase):
    pass

class UserBan(Base):
    __tablename__ = 'user_bans'
    id: Mapped[int] = mapped_column(primary_key=True)
    username: Mapped[str] = mapped_column(String, unique=True, index=True)
    ban_until: Mapped[datetime.datetime] = mapped_column(DateTime, nullable=True) # None = навсегда

class RouletteSession(Base):
    __tablename__ = 'roulette_sessions'
    chat_id: Mapped[int] = mapped_column(primary_key=True)
    is_active: Mapped[bool] = mapped_column(Boolean, default=False)
    trigger_symbol: Mapped[str] = mapped_column(String, default="+")
    winners_count: Mapped[int] = mapped_column(Integer, default=1)
    stop_time: Mapped[datetime.datetime] = mapped_column(DateTime)
    seed: Mapped[str] = mapped_column(String)
    salt: Mapped[str] = mapped_column(String)
    sha_hash: Mapped[str] = mapped_column(String)
    only_list_mode: Mapped[bool] = mapped_column(Boolean, default=False)

class RouletteParticipant(Base):
    __tablename__ = 'roulette_participants'
    id: Mapped[int] = mapped_column(primary_key=True)
    chat_id: Mapped[int] = mapped_column(Integer, index=True)
    username: Mapped[str] = mapped_column(String)
    user_id: Mapped[int] = mapped_column(Integer)
    msg_count: Mapped[int] = mapped_column(Integer, default=0) # Кол-во сообщений помимо плюса
    is_disqualified: Mapped[bool] = mapped_column(Boolean, default=False)

async def init_db():
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)

async def clean_expired_bans():
    """Очистка устаревших ограничений победоносцев"""
    async with async_session() as session:
        now = datetime.datetime.now(datetime.timezone.utc).replace(tzinfo=None)
        stmt = delete(UserBan).where(UserBan.ban_until < now)
        await session.execute(stmt)
        await session.commit()
