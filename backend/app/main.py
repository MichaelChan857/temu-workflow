"""FastAPI 应用入口"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from contextlib import asynccontextmanager
import logging
from pathlib import Path

from app.core.config import settings
from app.db.session import init_db
from app.api import reviews, import_csv, import_json, alerts, auth, users, publish, data_sources, scoring_config, listings, categories, category_sync, sales_feedback, drift, dedup

logging.basicConfig(level=logging.INFO)


@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    logging.info("Database initialized")
    yield


app = FastAPI(
    title=settings.APP_NAME,
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins_list,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 挂载静态资源（业务监控 UI）
STATIC_DIR = Path(__file__).parent.parent / "static"
if STATIC_DIR.exists():
    app.mount("/ui", StaticFiles(directory=str(STATIC_DIR), html=True), name="ui")

app.include_router(reviews.router)
app.include_router(import_csv.router)
app.include_router(import_json.router)
app.include_router(alerts.router)
app.include_router(auth.router)
app.include_router(users.router)
app.include_router(publish.router)
app.include_router(data_sources.router)
app.include_router(scoring_config.router)
app.include_router(listings.router)
app.include_router(categories.router)
app.include_router(category_sync.router)
app.include_router(sales_feedback.router)
app.include_router(drift.router)
app.include_router(dedup.router)


@app.get("/")
async def root():
    return {
        "app": settings.APP_NAME,
        "version": "0.1.0",
        "docs": "/docs",
        "temu_adapter": settings.TEMU_API_BASE,
        "ui": "/ui/dashboard.html",
    }