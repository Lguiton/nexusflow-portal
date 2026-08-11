from fastapi import FastAPI, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware

app = FastAPI(title="NexusFlow API Core")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000", "http://127.0.0.1:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/api/v1/healthcheck")
async def healthcheck():
    return {"status": "online", "service": "NexusFlow API Core"}

@app.get("/api/v1/analytics/summary")
async def analytics_summary():
    return {
        "total_mrr": 51000.0,
        "total_one_time": 5000.0,
        "active_clients": 2,
        "arpu": 8500.0,
        "gross_margin_percent": 82.5
    }

@app.post("/api/v1/etl/upload")
async def upload_file(file: UploadFile = File(...)):
    # Mock processing for now, returning success
    return {"filename": file.filename, "records_ingested": 3}
