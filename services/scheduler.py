from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.date import DateTrigger
from datetime import timedelta

scheduler = AsyncIOScheduler()

async def schedule_roulette_stop(roulette, bot):
    from services.roulette import finish_roulette
    scheduler.add_job(
        finish_roulette,
        trigger=DateTrigger(run_date=roulette.start_at + timedelta(minutes=roulette.duration_minutes)),
        args=[roulette.id, bot],
        id=f"roulette_stop_{roulette.id}"
    )

def setup_scheduler():
    scheduler.start()
    return scheduler
