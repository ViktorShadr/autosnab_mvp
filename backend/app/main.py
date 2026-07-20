from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import settings
from app.db.session import Base, engine
from app.models import *  # noqa: F401,F403
from app.routers import accounting, diadoc, google_oauth, invoice_review, receiving, receiving_backoffice, sbis
from app.services.database_health_service import assert_database_writable, database_health
from app.services.diadoc_scheduler_service import start_diadoc_scheduler, stop_diadoc_scheduler
from app.services.provider_health_service import provider_health
from app.services.sbis_scheduler_service import start_sbis_scheduler, stop_sbis_scheduler
from app.telegram_bot.bot import start_bot, stop_bot


@asynccontextmanager
async def lifespan(_app: FastAPI):
    Base.metadata.create_all(bind=engine)
    assert_database_writable(target_engine=engine)
    start_diadoc_scheduler()
    start_sbis_scheduler()
    await start_bot()
    try:
        yield
    finally:
        stop_diadoc_scheduler()
        stop_sbis_scheduler()
        await stop_bot()


app = FastAPI(title=settings.app_name, version="0.1.0", lifespan=lifespan)


@app.get("/ping")
def ping():
    return {"status": "ok", "service": settings.app_name}


@app.get("/health/runtime")
def health_runtime():
    database = database_health(target_engine=engine)
    return {
        "status": "ok" if database["ready"] else "degraded",
        "database": database,
    }


@app.get("/health/providers")
def health_providers():
    providers = provider_health()
    return {
        "status": "ok" if all(item["ready"] for item in providers.values()) else "degraded",
        "providers": providers,
    }


app.include_router(receiving.router, prefix=settings.api_prefix)
app.include_router(accounting.router, prefix=settings.api_prefix)
app.include_router(receiving_backoffice.router, prefix=settings.api_prefix)
app.include_router(google_oauth.router, prefix=settings.api_prefix)
app.include_router(invoice_review.router, prefix=settings.api_prefix)
app.include_router(diadoc.router, prefix=settings.api_prefix)
app.include_router(sbis.router, prefix=settings.api_prefix)
