import os

from fastapi import FastAPI
from fastapi.responses import FileResponse

BASE_DIR = os.path.dirname(os.path.abspath(__file__))

app = FastAPI(title="Technical Marketing Hub")


@app.get("/")
async def index():
    return FileResponse(os.path.join(BASE_DIR, "index.html"))
