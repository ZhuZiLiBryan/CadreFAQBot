from fastapi import FastAPI

app = FastAPI(title="Cadre FAQ Bot")


@app.get("/api/health")
async def health() -> dict[str, str]:
    return {"status": "ok"}
