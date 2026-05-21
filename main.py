from fastapi import FastAPI, HTTPException, BackgroundTasks, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from pydantic import BaseModel
import yt_dlp
import os
import uuid
from pathlib import Path

app = FastAPI(title="VidGrab API", version="1.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=False,
    allow_methods=["GET", "POST", "OPTIONS"],
    allow_headers=["*"],
    expose_headers=["Content-Disposition"],
)

DOWNLOAD_DIR = Path("downloads")
DOWNLOAD_DIR.mkdir(exist_ok=True)

class VideoInfoRequest(BaseModel):
    url: str

class DownloadRequest(BaseModel):
    url: str
    format: str
    quality: str

def cleanup_old_files():
    import time
    now = time.time()
    for f in DOWNLOAD_DIR.iterdir():
        if now - f.stat().st_mtime > 3600:
            f.unlink(missing_ok=True)

@app.get("/")
def root():
    return {"status": "ok", "message": "VidGrab API is running 🚀"}

@app.options("/info")
def options_info():
    return JSONResponse(content={}, headers={
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "POST, OPTIONS",
        "Access-Control-Allow-Headers": "*",
    })

@app.options("/download")
def options_download():
    return JSONResponse(content={}, headers={
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "POST, OPTIONS",
        "Access-Control-Allow-Headers": "*",
    })

@app.post("/info")
def get_video_info(req: VideoInfoRequest):
    ydl_opts = {
        "quiet": True,
        "no_warnings": True,
        "skip_download": True,
    }
    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(req.url, download=False)

        formats_available = []
        seen = set()
        for f in info.get("formats", []):
            height = f.get("height")
            if height and f.get("vcodec") != "none":
                label = f"{height}p"
                if label not in seen:
                    seen.add(label)
                    formats_available.append({
                        "label": label,
                        "height": height,
                        "filesize": f.get("filesize") or f.get("filesize_approx"),
                    })

        formats_available.sort(key=lambda x: x["height"], reverse=True)

        return {
            "title": info.get("title"),
            "channel": info.get("uploader"),
            "duration": info.get("duration"),
            "view_count": info.get("view_count"),
            "thumbnail": info.get("thumbnail"),
            "video_id": info.get("id"),
            "formats": formats_available,
        }

    except yt_dlp.utils.DownloadError as e:
        raise HTTPException(status_code=400, detail=f"Tidak bisa memproses URL: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/download")
def download_video(req: DownloadRequest, background_tasks: BackgroundTasks):
    cleanup_old_files()

    file_id = str(uuid.uuid4())
    output_path = DOWNLOAD_DIR / file_id

    if req.format == "mp3":
        bitrate_map = {"320kbps": "320", "192kbps": "192", "128kbps": "128"}
        bitrate = bitrate_map.get(req.quality, "192")
        ydl_opts = {
            "format": "bestaudio/best",
            "outtmpl": str(output_path) + ".%(ext)s",
            "quiet": True,
            "postprocessors": [{
                "key": "FFmpegExtractAudio",
                "preferredcodec": "mp3",
                "preferredquality": bitrate,
            }],
        }
        ext = "mp3"
    else:
        height_map = {
            "4K": "2160", "1080p": "1080", "720p": "720",
            "480p": "480", "360p": "360", "144p": "144"
        }
        height = height_map.get(req.quality, "1080")
        ydl_opts = {
            "format": f"bestvideo[height<={height}]+bestaudio/best[height<={height}]",
            "outtmpl": str(output_path) + ".%(ext)s",
            "quiet": True,
            "merge_output_format": "mp4",
        }
        ext = "mp4"

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(req.url, download=True)
            title = info.get("title", "video")

        downloaded = list(DOWNLOAD_DIR.glob(f"{file_id}.*"))
        if not downloaded:
            raise HTTPException(status_code=500, detail="File tidak ditemukan setelah download")

        file_path = downloaded[0]
        safe_title = "".join(c for c in title if c.isalnum() or c in " -_")[:60]
        filename = f"{safe_title}.{ext}"

        background_tasks.add_task(lambda p: p.unlink(missing_ok=True), file_path)

        return FileResponse(
            path=str(file_path),
            filename=filename,
            media_type="audio/mpeg" if ext == "mp3" else "video/mp4",
            headers={
                "Access-Control-Allow-Origin": "*",
                "Content-Disposition": f'attachment; filename="{filename}"',
            }
        )

    except yt_dlp.utils.DownloadError as e:
        raise HTTPException(status_code=400, detail=f"Download gagal: {str(e)}")
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
