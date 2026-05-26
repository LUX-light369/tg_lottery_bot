import zoneinfo
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from config import DATABASE_URL, DEFAULT_TZ

job_stores = {
    'default': SQLAlchemyJobStore(url=DATABASE_URL.replace("sqlite+aiosqlite", "sqlite"))
}

# Передаем таймзону Новосибирска в планировщик задач
scheduler = AsyncIOScheduler(
    jobstores=job_stores, 
    timezone=zoneinfo.ZoneInfo(DEFAULT_TZ)
)
