import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from . import jobs, storage
from .api import documents
from .api import library as library_api
from .api import services as services_api
from .api import settings as settings_api
from .config import ROOT, settings

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")

DIST = ROOT / "frontend" / "dist"


@asynccontextmanager
async def lifespan(_: FastAPI):
    storage.init(settings.data_dir)  # opens the DB and imports old JSON documents once
    jobs.start_worker()
    yield


app = FastAPI(title="Local Scan", lifespan=lifespan)
app.include_router(documents.router)
app.include_router(library_api.router)
app.include_router(settings_api.router)
app.include_router(services_api.router)

if DIST.exists():
    app.mount("/assets", StaticFiles(directory=DIST / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        f = DIST / path
        if path and f.is_file() and DIST in f.resolve().parents:
            return FileResponse(f)
        return FileResponse(DIST / "index.html")
