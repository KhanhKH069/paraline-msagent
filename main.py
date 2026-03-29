import os
import tempfile
from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel
import uvicorn

from inference.infer import VietnameseTTS

app = FastAPI(title="Vietnamese Bert-VITS2 API")

# Cache the TTS model so we don't reload it for every request
tts_model = None
current_checkpoint = None


class TTSRequest(BaseModel):
    text: str
    speaker_id: int = 0
    noise_scale: float = 0.667
    noise_scale_w: float = 0.8
    length_scale: float = 1.0
    checkpoint_path: str = "checkpoints/G_100000.pth"
    config_path: str = "configs/base_vi.json"


@app.get("/")
def health_check():
    return {"status": "ok", "message": "Vietnamese Bert-VITS2 API is running"}


@app.post("/tts")
def text_to_speech(req: TTSRequest):
    global tts_model, current_checkpoint

    # Check if checkpoint exists
    if not os.path.exists(req.checkpoint_path):
        raise HTTPException(
            status_code=400,
            detail=f"Checkpoint not found at: {req.checkpoint_path}. Please train a model or specify a valid checkpoint path.",
        )

    try:
        # Load or switch checkpoint if different
        if tts_model is None or current_checkpoint != req.checkpoint_path:
            tts_model = VietnameseTTS(
                checkpoint_path=req.checkpoint_path, config_path=req.config_path
            )
            current_checkpoint = req.checkpoint_path

        # Create a temporary file to save the target audio
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp_file:
            output_path = tmp_file.name

        # Synthesize audio
        tts_model.synthesize_to_file(
            text=req.text,
            output_path=output_path,
            speaker_id=req.speaker_id,
            noise_scale=req.noise_scale,
            noise_scale_w=req.noise_scale_w,
            length_scale=req.length_scale,
        )

        # Return the audio file using FileResponse
        return FileResponse(output_path, media_type="audio/wav", filename="output.wav")

    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
