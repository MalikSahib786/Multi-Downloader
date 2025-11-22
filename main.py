import os
import uvicorn
import yt_dlp
import requests
from fastapi import FastAPI, HTTPException, Header, Depends, Query
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(title="Pro Stream Downloader", version="5.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

MASTER_KEY = "123Lock.on"

class VideoRequest(BaseModel):
    url: str
    mode: str = "video"

async def verify_api_key(x_api_key: str = Header(None)):
    if x_api_key != MASTER_KEY:
        raise HTTPException(status_code=403, detail="Access Denied")

# --- HELPER TO GET DIRECT LINK ---
def get_direct_url(url, mode):
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'noplaylist': True,
        'force_ipv4': True,
        'nocheckcertificate': True,
        'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36', 
    }
    
    if mode == "audio":
        ydl_opts['format'] = 'bestaudio/best'
    else:
        ydl_opts['format'] = 'best[ext=mp4]/best'

    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=False)
        return info.get('url'), info.get('title', 'video')

@app.post("/extract", dependencies=[Depends(verify_api_key)])
def extract_info(request: VideoRequest):
    # This endpoint now generates a "Proxy Link" instead of a raw YouTube link
    return {
        "status": "success",
        "mode": request.mode,
        # We point the browser back to OUR server, not YouTube
        "download_url": f"/stream?url={request.url}&mode={request.mode}&key={MASTER_KEY}",
        "original_url": request.url
    }

# --- THE PROXY STREAMING ENDPOINT ---
@app.get("/stream")
def stream_video(url: str = Query(...), mode: str = Query("video"), key: str = Query(...)):
    """
    The Server downloads the file and passes it to the User (Bypasses 403 Error).
    """
    if key != MASTER_KEY:
        raise HTTPException(status_code=403, detail="Invalid Key")

    try:
        # 1. Get the locked URL (Server side)
        direct_url, title = get_direct_url(url, mode)
        
        # 2. Open a connection to YouTube (Server side)
        # We use stream=True so we don't load the whole file into RAM
        youtube_response = requests.get(direct_url, stream=True)
        
        # 3. Determine Filename and Type
        ext = "mp3" if mode == "audio" else "mp4"
        safe_title = "".join([c for c in title if c.isalnum() or c in " _-"])[:50]
        filename = f"{safe_title}.{ext}"
        media_type = "audio/mpeg" if mode == "audio" else "video/mp4"

        # 4. Stream it back to the user
        return StreamingResponse(
            youtube_response.iter_content(chunk_size=1024*1024), # 1MB chunks
            media_type=media_type,
            headers={"Content-Disposition": f'attachment; filename="{filename}"'}
        )

    except Exception as e:
        print(f"Stream Error: {e}")
        raise HTTPException(status_code=500, detail="Could not stream video")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
