from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles

from database import init_db
from routers import reservations, status

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    await init_db()
    logger.info("Database initialized")

    yield

    # Shutdown
    logger.info("Shutdown complete")


app = FastAPI(title="Restaurant Booking Agent", lifespan=lifespan)
app.include_router(reservations.router)
app.include_router(status.router)
app.mount("/", StaticFiles(directory="static", html=True), name="static")
