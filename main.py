import os
import uvicorn
import yt_dlp
from fastapi import FastAPI, HTTPException, Header, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(title="Pro All-In-One Downloader", version="4.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

MASTER_KEY = "123Lock.on"

# Update Model to accept 'mode'
class VideoRequest(BaseModel):
    url: str
    mode: str = "video"  # Options: "video" or "audio"

async def verify_api_key(x_api_key: str = Header(None)):
    if x_api_key != MASTER_KEY:
        raise HTTPException(status_code=403, detail="Access Denied")

@app.get("/")
def health_check():
    # Frontend calls this to check if API is Online
    return {"status": "Online", "message": "Server is ready"}

@app.post("/extract", dependencies=[Depends(verify_api_key)])
def extract_info(request: VideoRequest):
    url = request.url
    mode = request.mode.lower()
    print(f"⚡ Processing: {url} | Mode: {mode}")

    # Base Configuration
    ydl_opts = {
        'quiet': True,
        'no_warnings': True,
        'noplaylist': True,
        'force_ipv4': True,
        'nocheckcertificate': True,
        'socket_timeout': 30,
        # Mobile User Agent to avoid bot detection
        'user_agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1',
    }

    # --- FORMAT SELECTION LOGIC ---
    if mode == "audio":
        # Best Audio Only
        ydl_opts['format'] = 'bestaudio/best'
    else:
        # Best Video (MP4 preferred for compatibility)
        ydl_opts['format'] = 'best[ext=mp4]/best'

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            
            # Smart Extraction
            direct_url = info.get('url')
            
            # If direct URL is missing, hunt for the specific format
            if not direct_url and 'formats' in info:
                # If Audio Mode requested
                if mode == "audio":
                     for f in info['formats']:
                        if f.get('acodec') != 'none' and f.get('vcodec') == 'none':
                            direct_url = f['url']
                            break 
                # If Video Mode requested
                else:
                    for f in info['formats']:
                        if f.get('ext') == 'mp4' and f.get('vcodec') != 'none':
                            direct_url = f['url']
                            # Keep looking for better quality, but don't break immediately
            
            # Fallback
            if not direct_url:
                # Just grab the very last format (usually the highest quality available)
                if 'formats' in info and len(info['formats']) > 0:
                    direct_url = info['formats'][-1]['url']

            return {
                "status": "success",
                "mode": mode,
                "title": info.get('title') or "Unknown Video",
                "thumbnail": info.get('thumbnail'),
                "download_url": direct_url,
                "duration": info.get('duration'),
                "filesize": info.get('filesize_approx')
            }

    except Exception as e:
        error_msg = str(e)
        print(f"❌ Error: {error_msg}")
        if "Login" in error_msg:
            raise HTTPException(status_code=400, detail="Video is Private or Age Restricted.")
        raise HTTPException(status_code=500, detail="Failed to process video.")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
