"""
Ortho-Bender Web Dashboard - FastAPI application.
"""

from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse

from .motor.serial_client import client
from .routes import status_routes, motor_routes, bcode_routes, ws_routes


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    # Cleanup on shutdown
    client.disconnect()


app = FastAPI(
    title="Ortho-Bender Web Dashboard",
    version="0.1.0",
    lifespan=lifespan,
)

# Include routers
app.include_router(status_routes.router)
app.include_router(motor_routes.router)
app.include_router(bcode_routes.router)
app.include_router(ws_routes.router)

# Static files
static_dir = Path(__file__).parent.parent / "static"
app.mount("/static", StaticFiles(directory=str(static_dir)), name="static")


@app.get("/")
def index():
    return FileResponse(str(static_dir / "index.html"))


@app.get("/motor")
def motor_page():
    return FileResponse(str(static_dir / "motor.html"))


@app.get("/bcode")
def bcode_page():
    return FileResponse(str(static_dir / "bcode.html"))
