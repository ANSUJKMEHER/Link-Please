import os
import logging
from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from app.config import settings
from app.db import init_db
from app.worker import outbound_worker
from app.reconciler import delivery_reconciler
from app.routes import webhook, rules, stats, admin

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s"
)
logger = logging.getLogger("linkplease")

@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Initializing LinkPlease Engine...")
    await init_db()
    await outbound_worker.start()
    await delivery_reconciler.start()
    logger.info("LinkPlease Engine initialized and running.")
    yield
    logger.info("Shutting down LinkPlease Engine...")
    await outbound_worker.stop()
    await delivery_reconciler.stop()
    logger.info("LinkPlease Engine stopped.")

app = FastAPI(
    title=settings.APP_NAME,
    description="High-performance, fault-tolerant Instagram DM automation engine",
    version="1.0.0",
    lifespan=lifespan
)

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include core and auxiliary routes
app.include_router(webhook.router)
app.include_router(rules.router)
app.include_router(stats.router)
app.include_router(admin.router)

@app.get("/", summary="Health Check")
async def root_health():
    return {
        "status": "online",
        "service": "LinkPlease Instagram DM Automation Engine",
        "version": "1.0.0",
        "endpoints": {
            "webhook": "POST /webhook",
            "rules": "POST /rules",
            "stats": "GET /stats",
            "docs": "/docs"
        }
    }
