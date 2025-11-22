import os
import uvicorn
import yt_dlp
import subprocess
import shutil
from urllib.parse import quote, unquote
from fastapi import FastAPI, HTTPException, Header, Depends, Query
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(title="Final Media API", version="Native.1.0")

app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"],
)

MASTER_KEY = "123Lock.on"

# Mobile User Agent for Extraction
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

                        # Video
                        if f_ext == 'mp4' and f.get('vcodec') != 'none':
                            label = f"{f_res} ({size_str})"
                            formats_list.append({"type": "video", "label": label, "url": f['url']})
                        # Audio
                        elif f.get('vcodec') == 'none' and f.get('acodec') != 'none':
                             formats_list.append({"type": "audio", "label": f"Audio - {f_ext}", "url": f['url']})

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
        raise HTTPException(status_code=400, detail="Extraction Failed")

# --- THE NUCLEAR STREAMING FIX (SUBPROCESS) ---
@app.get("/stream")
def stream_content(target: str = Query(...), title: str = Query("file"), key: str = Query(...)):
    if key != MASTER_KEY:
        raise HTTPException(status_code=403, detail="Invalid Key")

    target_url = unquote(target)
    print(f"☢️ Native Streaming: {target_url[:50]}...")

    # Clean Filename
    safe_title = "".join([c for c in title if c.isalnum() or c in " _-"])[:50]
    if not safe_title: safe_title = "video"
    
    # Determine Extension
    ext = "mp4"
    if ".mp3" in target_url or "audio" in title.lower(): ext = "mp3"
    filename = f"{safe_title}.{ext}"

    # GENERATOR: Uses curl/ffmpeg system call instead of Python requests
    # This bypasses the TLS Fingerprint block from YouTube/CDN
    def iterfile():
        # We use yt-dlp to stream the direct URL to stdout
        # It handles headers/TLS automatically better than requests
        cmd = [
            "yt-dlp", 
            "--no-part", 
            "--quiet", 
            "--no-warnings", 
            "-o", "-",  # Output to Stdout
            target_url
        ]
        
        # If youtube, use specific UA
        if "googlevideo" in target_url:
            cmd.extend(["--user-agent", MOBILE_UA])

        try:
            # Open Subprocess
            process = subprocess.Popen(
                cmd,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL, # Hide errors
                bufsize=10**7 # 10MB Buffer
            )

            # Yield Data
            while True:
                chunk = process.stdout.read(64 * 1024) # Read 64KB
                if not chunk:
                    break
                yield chunk
            
            process.stdout.close()
            process.wait()

        except Exception as e:
            print(f"Native Stream Error: {e}")
    
    # Return Stream
    return StreamingResponse(
        iterfile(),
        media_type="application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
