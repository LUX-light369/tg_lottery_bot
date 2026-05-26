import zoneinfo
from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.jobstores.memory import MemoryJobStore
from config import DEFAULT_TZ

# Храним задачи в оперативной памяти, чтобы избежать падения с pickle/weakref
job_stores = {
    'default': MemoryJobStore()
}

scheduler = AsyncIOScheduler(
    jobstores=job_stores, 
    timezone=zoneinfo.ZoneInfo(DEFAULT_TZ)
)
