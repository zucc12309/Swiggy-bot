from contextlib import asynccontextmanager

from fastapi import FastAPI

from config.settings import settings
from src.api import webhooks
from src.db.database import engine
from src.models import Order, Schedule, ScheduleItem, User
from src.db.database import Base


@asynccontextmanager
async def lifespan(app: FastAPI):
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield


app = FastAPI(title="Swiggy Bot API", version="1.0.0", lifespan=lifespan)
app.include_router(webhooks.router)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "platform": settings.messaging_platform}
