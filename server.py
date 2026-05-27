from fastapi import FastAPI
from pydantic import BaseModel
from ai_detector import download_veo, run_return_dict

app = FastAPI()

class DetectRequest(BaseModel):
    veo_url: str
    shirt_number: str
    jersey_color: str

@app.post("/detect")
def detect(req: DetectRequest):
    input_path = req.veo_url

    if input_path.startswith("http"):
        input_path = download_veo(input_path)

    result = run_return_dict(input_path, req.shirt_number, req.jersey_color)
    return result

@app.get("/health")
def health():
    return {"status": "ok"}
