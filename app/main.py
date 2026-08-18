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

# Mount frontend static directory if exists
static_dir = os.path.join(os.path.dirname(os.path.dirname(__file__)), "static")
if os.path.exists(static_dir):
    app.mount("/assets", StaticFiles(directory=static_dir), name="static")

    @app.get("/", include_in_schema=False)
    async def serve_dashboard():
        index_file = os.path.join(static_dir, "index.html")
        if os.path.exists(index_file):
            return FileResponse(index_file)
        return {"status": "LinkPlease Instagram DM Automation Service Online"}
