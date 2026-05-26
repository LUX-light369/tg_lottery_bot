from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.jobstores.sqlalchemy import SQLAlchemyJobStore
from config import DATABASE_URL

# Храним задачи в SQL, чтобы они не стирались при перезапуске бота
job_stores = {
    'default': SQLAlchemyJobStore(url=DATABASE_URL.replace("sqlite+aiosqlite", "sqlite"))
}

scheduler = AsyncIOScheduler(jobstores=job_stores)
