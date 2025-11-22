import os
import uvicorn
import yt_dlp
import requests
import urllib3
from urllib.parse import quote, unquote
from fastapi import FastAPI, HTTPException, Header, Depends, Query
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# Disable SSL Warnings for older CDN compatibility
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

app = FastAPI(title="Social Media Downloader", version="Final.1.0")

app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"],
)

MASTER_KEY = "123Lock.on"

# --- KEY CONFIGURATION ---
# We use a generic iPhone User Agent. 
# Social Media sites (TikTok/IG) trust mobile devices more than desktops.
MOBILE_UA = 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1'

class MediaRequest(BaseModel):
    url: str

async def verify_api_key(x_api_key: str = Header(None)):
    if x_api_key != MASTER_KEY:
        raise HTTPException(status_code=403, detail="Access Denied")

def format_size(bytes_size):
    if not bytes_size: return "Unknown Size"
    return f"{round(bytes_size / 1024 / 1024, 1)} MB"

@app.post("/extract", dependencies=[Depends(verify_api_key)])
def extract_media(request: MediaRequest):
    url = request.url
    print(f"📱 Processing Social Media: {url}")

    try:
        # yt-dlp Configuration for Social Media
        ydl_opts = {
            'quiet': True, 'no_warnings': True, 'noplaylist': True,
            'force_ipv4': True, 'nocheckcertificate': True,
            'user_agent': MOBILE_UA, # Strict Identity
            'socket_timeout': 15,
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            # Extract Info
            info = ydl.extract_info(url, download=False)
            formats_list = []
            duration = info.get('duration', 0)
            
            # Loop through formats to find best options
            if 'formats' in info:
                for f in info['formats']:
                    if f.get('url'):
                        f_ext = f.get('ext')
                        f_res = f.get('resolution') or f"{f.get('height')}p"
                        
                        # Size Calc
                        size = f.get('filesize') or f.get('filesize_approx')
                        if not size and f.get('tbr') and duration:
                            size = (f.get('tbr') * 1024 * duration) / 8
                        
                        size_str = format_size(size)

                        # 1. Video (MP4)
                        if f_ext == 'mp4' and f.get('vcodec') != 'none':
                            # Check for Audio
                            has_audio = "🔇 No Audio" if f.get('acodec') == 'none' else "🔊 With Audio"
                            
                            # Clean Label
                            label = f"{f_res} ({size_str}) {has_audio}"
                            
                            formats_list.append({
                                "type": "video",
                                "label": label,
                                "url": f['url']
                            })
                        
                        # 2. Audio Only (m4a/mp3)
                        elif f.get('vcodec') == 'none' and f.get('acodec') != 'none':
                             formats_list.append({
                                "type": "audio",
                                "label": f"Audio Only - {f_ext} ({size_str})",
                                "url": f['url']
                            })

            # Fallback if no specific formats found (Common in TikTok/Reels)
            if not formats_list:
                 direct_url = info.get('url')
                 if direct_url:
                     formats_list.append({"type": "video", "label": "Best Quality (Auto)", "url": direct_url})

            # Sort: Best resolution first
            formats_list.reverse()

            return {
                "status": "success",
                "title": info.get('title') or "Social Media Video",
                "thumbnail": info.get('thumbnail'),
                "source": info.get('extractor_key'),
                "options": formats_list
            }

    except Exception as e:
        print(f"Extraction Error: {e}")
        # Identify specific errors
        err = str(e)
        if "Login" in err:
            raise HTTPException(status_code=400, detail="Private Video (Login Required)")
        if "Geo" in err:
            raise HTTPException(status_code=400, detail="Geo-Blocked Video")
            
        raise HTTPException(status_code=404, detail="Could not find video. Check URL.")

# --- STREAMING ENDPOINT (The 403 Fix) ---
@app.get("/stream")
def stream_content(target: str = Query(...), title: str = Query("file"), key: str = Query(...)):
    if key != MASTER_KEY:
        raise HTTPException(status_code=403, detail="Invalid Key")

    try:
        target_url = unquote(target)
        
        # --- HEADER STRATEGY ---
        # We MUST mirror the headers used in extraction (Mobile UA)
        # But we must adjust 'Referer' based on the domain.
        headers = {'User-Agent': MOBILE_UA}
        
        # Domain Specific Rules
        if "tiktok.com" in target_url or "byteoversea" in target_url:
            headers['Referer'] = 'https://www.tiktok.com/'
            
        elif "googlevideo.com" in target_url:
            # YouTube often prefers NO headers for signed URLs
            headers = {} 
            
        elif "fbcdn" in target_url:
            # Facebook needs User Agent
            headers = {'User-Agent': MOBILE_UA}

        # --- CONNECTION ---
        # stream=True (Low RAM), verify=False (Fix SSL errors), timeout=(Connect, Read)
        external_req = requests.get(target_url, headers=headers, stream=True, verify=False, timeout=(10, 60))
        
        # --- RETRY LOGIC (If 403 Forbidden) ---
        if external_req.status_code == 403:
            print("403 Blocked. Retrying with Desktop User Agent...")
            # Fallback to Desktop Chrome if Mobile fails
            desktop_ua = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            external_req = requests.get(target_url, headers={'User-Agent': desktop_ua}, stream=True, verify=False, timeout=30)

        if external_req.status_code >= 400:
            print(f"Stream Failed: {external_req.status_code}")
            raise HTTPException(status_code=400, detail=f"Source Blocked ({external_req.status_code}). Link Expired.")

        # --- RESPONSE SETUP ---
        content_type = external_req.headers.get('content-type', 'application/octet-stream')
        safe_title = "".join([c for c in title if c.isalnum() or c in " _-"])[:40]
        
        ext = "mp4"
        if "audio" in content_type: ext = "mp3"
        if "image" in content_type: ext = "jpg"
        
        filename = f"{safe_title}.{ext}"

        return StreamingResponse(
            external_req.iter_content(chunk_size=64*1024),
            media_type=content_type,
            headers={"Content-Disposition": f'attachment; filename="{filename}"'}
        )

    except Exception as e:
        print(f"Stream Critical: {e}")
        raise HTTPException(status_code=500, detail="Stream Connection Failed")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
