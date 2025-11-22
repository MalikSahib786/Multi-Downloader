import os
import uvicorn
import yt_dlp
import requests
import urllib3
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from urllib.parse import quote, unquote
from fastapi import FastAPI, HTTPException, Header, Depends, Query
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# 1. Disable SSL Warnings (Fixes connection to older CDNs)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

app = FastAPI(title="Social Media Downloader", version="Expert.1.0")

app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"],
)

MASTER_KEY = "123Lock.on"
MOBILE_UA = 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1'

class MediaRequest(BaseModel):
    url: str

async def verify_api_key(x_api_key: str = Header(None)):
    if x_api_key != MASTER_KEY:
        raise HTTPException(status_code=403, detail="Access Denied")

def format_size(bytes_size):
    if not bytes_size: return "Unknown Size"
    return f"{round(bytes_size / 1024 / 1024, 1)} MB"

# --- 2. ROBUST NETWORK SESSION (The Fix) ---
def get_session():
    """
    Creates a connection that automatically retries if it fails.
    """
    session = requests.Session()
    # Retry 3 times on: 500 Errors, 502 Gateway, 503 Service Unavailable, 504 Gateway Timeout
    retries = Retry(total=3, backoff_factor=1, status_forcelist=[500, 502, 503, 504])
    adapter = HTTPAdapter(max_retries=retries)
    session.mount('https://', adapter)
    session.mount('http://', adapter)
    return session

@app.post("/extract", dependencies=[Depends(verify_api_key)])
def extract_media(request: MediaRequest):
    url = request.url
    print(f"📱 Analyzing: {url}")

    try:
        ydl_opts = {
            'quiet': True, 'no_warnings': True, 'noplaylist': True,
            'force_ipv4': True, 'nocheckcertificate': True,
            'user_agent': MOBILE_UA,
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

                        # Video (MP4)
                        if f_ext == 'mp4' and f.get('vcodec') != 'none':
                            label = f"{f_res} ({size_str})"
                            formats_list.append({"type": "video", "label": label, "url": f['url']})
                        
                        # Audio Only
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
                "source": info.get('extractor_key'),
                "options": formats_list
            }

    except Exception as e:
        print(f"Extraction Failed: {e}")
        err = str(e)
        if "Login" in err: raise HTTPException(status_code=400, detail="Private Video (Login Required)")
        raise HTTPException(status_code=404, detail="Could not find video.")

# --- 3. EXPERT STREAMING ENDPOINT ---
@app.get("/stream")
def stream_content(target: str = Query(...), title: str = Query("file"), key: str = Query(...)):
    if key != MASTER_KEY:
        raise HTTPException(status_code=403, detail="Invalid Key")

    target_url = unquote(target)
    
    # Headers Logic
    headers = {'User-Agent': MOBILE_UA}
    if "tiktok.com" in target_url or "byteoversea" in target_url:
        headers['Referer'] = 'https://www.tiktok.com/'
    elif "googlevideo.com" in target_url:
        headers = {} # YouTube often requires empty headers for signed URLs

    try:
        session = get_session()
        
        # CONNECTION ATTEMPT
        # stream=True is vital. verify=False ignores SSL errors. timeout=(Connect, Read)
        req = session.get(target_url, headers=headers, stream=True, verify=False, timeout=(10, 60))

        # RETRY LOGIC (If Mobile UA fails, try Desktop UA)
        if req.status_code in [403, 401]:
            print(f"⚠️ Mobile UA Blocked ({req.status_code}). Retrying with Desktop...")
            desktop_ua = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'
            req = session.get(target_url, headers={'User-Agent': desktop_ua}, stream=True, verify=False, timeout=(10, 60))
        
        # FINAL CHECK
        if req.status_code >= 400:
            print(f"❌ UPSTREAM ERROR: {req.status_code} | URL: {target_url[:50]}...")
            raise HTTPException(status_code=400, detail=f"Source Blocked: {req.status_code}")

        # PREPARE STREAM
        content_type = req.headers.get('content-type', 'application/octet-stream')
        safe_title = "".join([c for c in title if c.isalnum() or c in " _-"])[:50]
        ext = "mp4"
        if "audio" in content_type: ext = "mp3"
        filename = f"{safe_title}.{ext}"

        # YIELD CONTENT (Prevents Memory Crash)
        def iterfile():
            try:
                for chunk in req.iter_content(chunk_size=64*1024):
                    if chunk: yield chunk
            except Exception as e:
                print(f"❌ Connection Dropped mid-stream: {e}")

        return StreamingResponse(
            iterfile(),
            media_type=content_type,
            headers={"Content-Disposition": f'attachment; filename="{filename}"'}
        )

    # --- 4. SPECIFIC ERROR HANDLING ---
    except requests.exceptions.SSLError as e:
        print(f"❌ SSL Error: {e}")
        raise HTTPException(status_code=502, detail="Source SSL Certificate Error")
    except requests.exceptions.ConnectionError as e:
        print(f"❌ Connection Error: {e}")
        raise HTTPException(status_code=502, detail="Could not connect to video server")
    except requests.exceptions.Timeout as e:
        print(f"❌ Timeout: {e}")
        raise HTTPException(status_code=504, detail="Source took too long to respond")
    except Exception as e:
        print(f"❌ UNKNOWN ERROR: {e}")
        raise HTTPException(status_code=500, detail=f"System Error: {str(e)}")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
