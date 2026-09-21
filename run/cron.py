
# OOP Refactor
import sys
import asyncio
import logging
import json
from pathlib import Path
import tempfile

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apps.app.utils.redis import get_redis_init
from infra.redis_keys import cron_jobs_registry as CRON_JOBS_KEY

class CronManager:
    def __init__(self):
        self.scheduler = None
        self.logger = logging.getLogger("cron.manager")
        logging.getLogger("apscheduler.executors.default").setLevel(logging.ERROR)

    def get_scheduler(self):
        if self.scheduler is None:
            self.scheduler = AsyncIOScheduler()
            self.scheduler.start()
        return self.scheduler

    def list_cron_jobs(self):
        with get_redis_init() as r:
            keys = r.keys(f"{CRON_JOBS_KEY}::*")
        if not keys:
            print("No running cron jobs.")
            return
        with get_redis_init() as r:
            jobs = [json.loads(r.get(k)) for k in keys if r.get(k)]
        print("Registered cron jobs:")
        for job in jobs:
            last_run = job.get('last_run', 'Unknown')
            next_run = job.get('next_run', 'Unknown')
            schedule = job.get('cron_expr') or job.get('interval_kwargs', {})
            print(f"- {job['function']} (module: {job['module']}, schedule: {schedule})\n    Last run: {last_run}\n    Next run: {next_run}")

def main():
    manager = CronManager()
    if len(sys.argv) > 1 and sys.argv[1] == "list":
        asyncio.run(asyncio.to_thread(manager.list_cron_jobs))
    else:
        print("Usage: python -m run.cron list")

if __name__ == "__main__":
    main()
