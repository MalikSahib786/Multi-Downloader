import os
import uvicorn
import yt_dlp
from fastapi import FastAPI, HTTPException, Header, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(title="All-In-One Downloader", version="3.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- CREDENTIALS ---
MASTER_KEY = "123Lock.on"

class VideoRequest(BaseModel):
    url: str

async def verify_api_key(x_api_key: str = Header(None)):
    if x_api_key != MASTER_KEY:
        raise HTTPException(status_code=403, detail="Access Denied")

@app.get("/")
def home():
    return {"status": "Online", "supports": "YouTube, TikTok, FB, IG, Twitter, etc."}

@app.post("/extract", dependencies=[Depends(verify_api_key)])
def extract_video_info(request: VideoRequest):
    url = request.url
    print(f"⚡ Processing: {url}")

    # --- ALL-IN-ONE CONFIGURATION ---
    ydl_opts = {
        'format': 'best',  # Social media sites usually have 1 "best" file
        'quiet': True,
        'no_warnings': True,
        'noplaylist': True,
        'extract_flat': False,
        
        # NETWORK & SECURITY
        'force_ipv4': True,
        'nocheckcertificate': True,
        'socket_timeout': 30,
        
        # --- TRICK FOR TIKTOK / INSTAGRAM ---
        # We pretend to be an iPhone. This stops them from blocking "Bots".
        'user_agent': 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1',
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            
            # 1. Direct URL Logic (Works for TikTok/FB/IG)
            direct_url = info.get('url')
            
            # 2. YouTube Fallback Logic (If 'url' is empty, check formats)
            if not direct_url and 'formats' in info:
                # Try to find mp4 with audio
                for f in info['formats']:
                    if f.get('ext') == 'mp4' and f.get('vcodec') != 'none' and f.get('acodec') != 'none':
                        direct_url = f['url']
                        # Don't break immediately, keep looking for better quality
                        # But if it's the only one, we take it.
                
                # If still no URL, just take the last available format (usually best)
                if not direct_url:
                    direct_url = info['formats'][-1]['url']

            return {
                "status": "success",
                "platform": info.get('extractor_key', 'Unknown'), # e.g., 'TikTok', 'Instagram'
                "title": info.get('title') or info.get('description') or "Video",
                "thumbnail": info.get('thumbnail'),
                "download_url": direct_url,
                "duration": info.get('duration')
            }

    except Exception as e:
        error_msg = str(e)
        print(f"❌ Error: {error_msg}")
        if "Login" in error_msg:
            raise HTTPException(status_code=400, detail="This video is Private or requires Login.")
        raise HTTPException(status_code=500, detail="Could not fetch video. Link might be broken or private.")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
