from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import router

app = FastAPI(
    title="Butler Task Lifecycle Tracer",
    description="Read-only observability tool - see README.md for scope.",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # internal tool behind VPN; tighten if exposed more broadly
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)


@app.get("/health")
def health():
    return {"status": "ok"}
