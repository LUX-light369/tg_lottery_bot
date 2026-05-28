from sqlalchemy import Integer, BigInteger, String, Text, DateTime, JSON, Boolean
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from datetime import datetime
from typing import Optional, List

class Base(DeclarativeBase):
    pass

class ChatSettings(Base):
    __tablename__ = "chat_settings"
    id: Mapped[int] = mapped_column(primary_key=True)
    chat_id: Mapped[int] = mapped_column(BigInteger, index=True)
    module: Mapped[str] = mapped_column(String(20))   # 'giveaway', 'roulette'
    data: Mapped[dict] = mapped_column(JSON, default=dict)

class Giveaway(Base):
    __tablename__ = "giveaways"
    id: Mapped[int] = mapped_column(primary_key=True)
    chat_id: Mapped[int] = mapped_column(BigInteger)
    creator_id: Mapped[int] = mapped_column(BigInteger)
    post_message_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    status: Mapped[str] = mapped_column(String(20), default="active")
    mode: Mapped[str] = mapped_column(String(20))            # time/participants
    end_time: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    max_participants: Mapped[Optional[int]] = mapped_column(Integer, nullable=True)
    winner_count: Mapped[int] = mapped_column(Integer, default=1)
    prizes: Mapped[list] = mapped_column(JSON, default=list)
    seed: Mapped[Optional[str]] = mapped_column(String(64))
    seed_hash: Mapped[Optional[str]] = mapped_column(String(64))
    check_channels: Mapped[list] = mapped_column(JSON, default=list)
    extra_condition: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    post_text: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    post_media: Mapped[Optional[str]] = mapped_column(Text, nullable=True)
    participants: Mapped[list] = mapped_column(JSON, default=list)
    winners: Mapped[list] = mapped_column(JSON, default=list)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class Roulette(Base):
    __tablename__ = "roulettes"
    id: Mapped[int] = mapped_column(primary_key=True)
    chat_id: Mapped[int] = mapped_column(BigInteger)
    creator_id: Mapped[int] = mapped_column(BigInteger)
    status: Mapped[str] = mapped_column(String(20), default="waiting")
    start_message_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    stop_message_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    winner_count: Mapped[int] = mapped_column(Integer, default=1)
    prizes: Mapped[list] = mapped_column(JSON, default=list)
    start_at: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    duration_minutes: Mapped[int] = mapped_column(Integer, default=5)
    seed: Mapped[Optional[str]] = mapped_column(String(64))
    seed_hash: Mapped[Optional[str]] = mapped_column(String(64))
    trigger_list: Mapped[list] = mapped_column(JSON, default=["+"])
    participants: Mapped[list] = mapped_column(JSON, default=list)
    winners: Mapped[list] = mapped_column(JSON, default=list)
    muted_users: Mapped[list] = mapped_column(JSON, default=list)
    result_message_id: Mapped[Optional[int]] = mapped_column(BigInteger, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)

class Restriction(Base):
    __tablename__ = "restrictions"
    id: Mapped[int] = mapped_column(primary_key=True)
    user_id: Mapped[int] = mapped_column(BigInteger, index=True)
    username: Mapped[Optional[str]] = mapped_column(String(100))
    module: Mapped[str] = mapped_column(String(20))
    restricted_until: Mapped[Optional[datetime]] = mapped_column(DateTime, nullable=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.utcnow)
