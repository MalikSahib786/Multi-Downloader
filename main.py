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

# SSL Warnings Disable (Zaroori hai)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

app = FastAPI(title="Social Downloader Pro", version="Fixed.2.0")

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

@app.post("/extract", dependencies=[Depends(verify_api_key)])
def extract_media(request: MediaRequest):
    url = request.url
    print(f"⚡ Extracting: {url}")

    try:
        # Extraction Configuration
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

            # Formats Filtering
            if 'formats' in info:
                for f in info['formats']:
                    if f.get('url'):
                        f_ext = f.get('ext')
                        f_res = f.get('resolution') or f"{f.get('height')}p"
                        
                        size = f.get('filesize') or f.get('filesize_approx')
                        if not size and f.get('tbr') and duration:
                            size = (f.get('tbr') * 1024 * duration) / 8
                        size_str = format_size(size)

                        # MP4 Video
                        if f_ext == 'mp4' and f.get('vcodec') != 'none':
                            label = f"{f_res} ({size_str})"
                            formats_list.append({"type": "video", "label": label, "url": f['url']})
                        # Audio Only
                        elif f.get('vcodec') == 'none' and f.get('acodec') != 'none':
                             formats_list.append({"type": "audio", "label": f"Audio - {f_ext}", "url": f['url']})

            if not formats_list:
                 direct = info.get('url')
                 if direct: formats_list.append({"type": "video", "label": "Auto Quality", "url": direct})

            formats_list.reverse()

            return {
                "status": "success",
                "title": info.get('title'),
                "thumbnail": info.get('thumbnail'),
                "options": formats_list
            }

    except Exception as e:
        print(f"Extraction Error: {e}")
        raise HTTPException(status_code=400, detail=f"Extraction Failed: {str(e)}")

# --- STREAMING FIX ---
@app.get("/stream")
def stream_content(target: str = Query(...), title: str = Query("file"), key: str = Query(...)):
    if key != MASTER_KEY:
        raise HTTPException(status_code=403, detail="Invalid Key")

    target_url = unquote(target)
    print(f"🌊 Streaming Request for: {title}")

    try:
        # 1. Headers Setup
        headers = {
            'User-Agent': MOBILE_UA,
            'Accept': '*/*',
            'Connection': 'keep-alive'
        }
        
        # 2. Platform Specific Rules
        if "tiktok.com" in target_url or "byteoversea" in target_url:
            headers['Referer'] = 'https://www.tiktok.com/'
        elif "googlevideo.com" in target_url:
            # YouTube links are signed. Sending headers often breaks them.
            headers = {} 

        # 3. Connect with INCREASED TIMEOUT (30s connect, 120s read)
        # stream=True is REQUIRED. verify=False prevents SSL errors.
        r = requests.get(target_url, headers=headers, stream=True, verify=False, timeout=(30, 120))

        # 4. Check Status Code
        if r.status_code >= 400:
            print(f"❌ Blocked: {r.status_code}")
            # Return the exact error code so we know what happened
            raise HTTPException(status_code=400, detail=f"Source Blocked (Code: {r.status_code})")

        # 5. Prepare File Metadata
        content_type = r.headers.get('content-type', 'application/octet-stream')
        safe_title = "".join([c for c in title if c.isalnum() or c in " _-"])[:40]
        
        ext = "mp4"
        if "audio" in content_type: ext = "mp3"
        if "image" in content_type: ext = "jpg"
        
        filename = f"{safe_title}.{ext}"

        # 6. Stream Generator (Safe Yield)
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

    # 7. CATCH SPECIFIC ERRORS (This is what you need to see)
    except requests.exceptions.ConnectTimeout:
        print("❌ Error: ConnectTimeout")
        raise HTTPException(status_code=504, detail="Error: Server Connection Timed Out")
    except requests.exceptions.ReadTimeout:
        print("❌ Error: ReadTimeout")
        raise HTTPException(status_code=504, detail="Error: Download took too long")
    except requests.exceptions.SSLError as e:
        print(f"❌ Error: SSL {e}")
        raise HTTPException(status_code=502, detail="Error: SSL Handshake Failed")
    except requests.exceptions.ConnectionError as e:
        print(f"❌ Error: ConnectionError {e}")
        raise HTTPException(status_code=502, detail=f"Error: Network Failed ({str(e)})")
    except Exception as e:
        # CATCH ALL
        print(f"❌ CRITICAL: {str(e)}")
        raise HTTPException(status_code=500, detail=f"System Error: {str(e)}")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
