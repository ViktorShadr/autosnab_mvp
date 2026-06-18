from fastapi import FastAPI

from app.config import settings
from app.db.session import Base, engine
from app.models import *  # noqa: F401,F403
from app.routers import accounting, mvp3, receiving

Base.metadata.create_all(bind=engine)

app = FastAPI(title=settings.app_name, version="0.1.0")


@app.get("/ping")
def ping():
    return {"status": "ok", "service": settings.app_name}


app.include_router(receiving.router, prefix=settings.api_prefix)
app.include_router(accounting.router, prefix=settings.api_prefix)
app.include_router(mvp3.router, prefix=settings.api_prefix)
