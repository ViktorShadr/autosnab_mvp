from fastapi import FastAPI
from app.config import settings
from app.db.session import Base, engine
from app.models import *  # noqa: F401,F403
from app.routers import accounting, google_oauth, invoice_review, receiving, receiving_backoffice
from app.services.provider_health_service import provider_health

Base.metadata.create_all(bind=engine)

app = FastAPI(title=settings.app_name, version="0.1.0")


@app.get("/ping")
def ping():
    return {"status": "ok", "service": settings.app_name}


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
