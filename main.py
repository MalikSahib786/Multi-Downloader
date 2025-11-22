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

# Disable SSL Warnings
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

app = FastAPI(title="Social Media Downloader", version="Expert.Final")

app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"],
)

MASTER_KEY = "123Lock.on"

# --- IDENTITY CONFIGURATION ---
# We stick to ONE identity. Do not change this.
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
    print(f"📱 Extracting: {url}")

    try:
        ydl_opts = {
            'quiet': True, 'no_warnings': True, 'noplaylist': True,
            'force_ipv4': True, 'nocheckcertificate': True,
            'user_agent': MOBILE_UA, # IMPORTANT: Must match Streaming UA
            'socket_timeout': 15,
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            formats_list = []
            duration = info.get('duration', 0)

            if 'formats' in info:
                for f in info['formats']:
                    if f.get('url'):
                        f_ext = f.get('ext')
                        f_res = f.get('resolution') or f"{f.get('height')}p"
                        
                        size = f.get('filesize') or f.get('filesize_approx')
                        if not size and f.get('tbr') and duration:
                            size = (f.get('tbr') * 1024 * duration) / 8
                        
                        size_str = format_size(size)

                        # Video
                        if f_ext == 'mp4' and f.get('vcodec') != 'none':
                            label = f"{f_res} ({size_str})"
                            formats_list.append({"type": "video", "label": label, "url": f['url']})
                        # Audio
                        elif f.get('vcodec') == 'none' and f.get('acodec') != 'none':
                             formats_list.append({"type": "audio", "label": f"Audio - {f_ext} ({size_str})", "url": f['url']})

            if not formats_list:
                 direct_url = info.get('url')
                 if direct_url: formats_list.append({"type": "video", "label": "Best Quality", "url": direct_url})

            formats_list.reverse()

            return {
                "status": "success",
                "title": info.get('title') or "Video",
                "thumbnail": info.get('thumbnail'),
                "options": formats_list
            }

    except Exception as e:
        print(f"Extraction Error: {e}")
        raise HTTPException(status_code=400, detail=f"Extraction Failed: {str(e)}")

# --- STREAMING ENDPOINT (THE 403 FIX) ---
@app.get("/stream")
def stream_content(target: str = Query(...), title: str = Query("file"), key: str = Query(...)):
    if key != MASTER_KEY:
        raise HTTPException(status_code=403, detail="Invalid Key")

    target_url = unquote(target)
    print(f"🌊 Streaming: {title}")

    try:
        # Use a Session to handle Cookies automatically (Fixes many 403s)
        session = requests.Session()
        
        # HEADERS STRATEGY:
        # 1. User-Agent: Must match extraction (Mobile)
        # 2. Range: "bytes=0-" (Tricks server into thinking we are a video player buffering)
        # 3. Referer: Only for TikTok
        
        headers = {
            'User-Agent': MOBILE_UA,
            'Accept': '*/*',
            'Accept-Encoding': 'identity;q=1, *;q=0',
            'Range': 'bytes=0-',  # <--- THE MAGIC HEADER
            'Connection': 'keep-alive'
        }
        
        # Domain Specifics
        if "tiktok.com" in target_url or "byteoversea" in target_url:
            headers['Referer'] = 'https://www.tiktok.com/'
        
        # YouTube Logic:
        # YouTube checks if the IP downloading matches the IP extracting.
        # Since we are on Railway for both, IP matches.
        # The 403 comes from Headers. We try Mobile UA first.
        
        # ATTEMPT 1: Mobile Identity + Range Header
        r = session.get(target_url, headers=headers, stream=True, verify=False, timeout=(10, 60))
        
        # ATTEMPT 2: If 403, Retry with Clean Slate (No Headers)
        if r.status_code == 403:
            print("⚠️ 403 Blocked. Retrying with Clean Headers...")
            # Sometimes sending NO User-Agent works better for signed URLs
            r = requests.get(target_url, stream=True, verify=False, timeout=(10, 60))

        # ATTEMPT 3: If still 403, Retry with Desktop UA
        if r.status_code == 403:
            print("⚠️ Still 403. Retrying with Desktop UA...")
            desk_ua = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            r = requests.get(target_url, headers={'User-Agent': desk_ua}, stream=True, verify=False, timeout=(10, 60))

        # FINAL ERROR CHECK
        if r.status_code >= 400:
            print(f"❌ FATAL ERROR: {r.status_code}")
            raise HTTPException(status_code=400, detail=f"Source Blocked (Code: {r.status_code}). Link expired or IP blacklisted.")

        # Prepare Stream
        content_type = r.headers.get('content-type', 'application/octet-stream')
        safe_title = "".join([c for c in title if c.isalnum() or c in " _-"])[:40]
        
        ext = "mp4"
        if "audio" in content_type: ext = "mp3"
        if "image" in content_type: ext = "jpg"
        
        filename = f"{safe_title}.{ext}"

        # Streaming Generator
        def iterfile():
            try:
                for chunk in r.iter_content(chunk_size=64*1024):
                    if chunk: yield chunk
            except Exception as e:
                print(f"⚠️ Stream Cutoff: {e}")

        return StreamingResponse(
            iterfile(),
            media_type=content_type,
            headers={"Content-Disposition": f'attachment; filename="{filename}"'}
        )

    except Exception as e:
        print(f"System Error: {e}")
        raise HTTPException(status_code=500, detail=f"Connection Failed: {str(e)}")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
