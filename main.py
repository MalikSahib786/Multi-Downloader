import os
import uvicorn
import yt_dlp
import subprocess
from urllib.parse import quote, unquote
from fastapi import FastAPI, HTTPException, Header, Depends, Query
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(title="Social Media API", version="Cookies.Pro")

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
    raw_url = request.url
    url = raw_url.replace("x.com", "twitter.com")
    print(f"📱 Extracting: {url}")

    if "facebook.com/watch/" in url and "?v=" not in url and "videos/" not in url:
        raise HTTPException(status_code=400, detail="Invalid FB Link")

    try:
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'noplaylist': True,
            'force_ipv4': True,
            'nocheckcertificate': True,
            'socket_timeout': 15,
        }

        # --- COOKIE LOADER ---
        # This is the fix for "Sign in required"
        if os.path.exists("cookies.txt"):
            ydl_opts['cookiefile'] = "cookies.txt"

        # --- YOUTUBE SPECIFIC CONFIG ---
        if "youtube.com" in url or "youtu.be" in url:
             ydl_opts['extractor_args'] = {
                'youtube': {
                    'player_client': ['android', 'web'], # Mimic Android App + Web
                    'player_skip': ['webpage', 'configs', 'js'],
                    'include_ssr': False
                }
            }
        else:
            ydl_opts['user_agent'] = MOBILE_UA

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
                            size = int((f.get('tbr') * 1024 * duration) / 8)
                        
                        size_str = format_size(size)

                        if f_ext == 'mp4' and f.get('vcodec') != 'none':
                            formats_list.append({"type": "video", "label": f"{f_res} ({size_str})", "url": f['url'], "filesize": size})
                        elif f.get('vcodec') == 'none' and f.get('acodec') != 'none':
                             formats_list.append({"type": "audio", "label": f"Audio - {f_ext}", "url": f['url'], "filesize": size})

            if not formats_list:
                 direct_url = info.get('url')
                 if direct_url: formats_list.append({"type": "video", "label": "Best Quality", "url": direct_url, "filesize": 0})

            formats_list.reverse()

            return {
                "status": "success",
                "title": info.get('title'),
                "thumbnail": info.get('thumbnail'),
                "options": formats_list
            }

    except Exception as e:
        print(f"Extraction Error: {e}")
        err_msg = str(e)
        if "Sign in" in err_msg:
             raise HTTPException(status_code=400, detail="YouTube Blocked Server IP. Please update cookies.txt")
        raise HTTPException(status_code=400, detail="Could not find media.")

@app.get("/stream")
def stream_content(target: str = Query(...), title: str = Query("file"), size: int = Query(None), key: str = Query(...)):
    if key != MASTER_KEY:
        raise HTTPException(status_code=403, detail="Invalid Key")

    target_url = unquote(target)
    
    ext = "mp4"
    if ".jpg" in target_url or "yt3.ggpht" in target_url: ext = "jpg"
    elif ".mp3" in target_url or "audio" in title.lower(): ext = "mp3"
    
    try:
        ascii_title = title.encode('ascii', 'ignore').decode('ascii')
    except: ascii_title = "video"
    safe_title = "".join([c for c in ascii_title if c.isalnum() or c in " _-"])[:50]
    if not safe_title: safe_title = "download"
    filename = f"{safe_title}.{ext}"

    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
    if size and size > 0: headers["Content-Length"] = str(size)

    def iterfile():
        cmd = ["yt-dlp", "--no-part", "--quiet", "--no-warnings", "-o", "-", target_url]
        
        # Use Cookies for Streaming too if it's YouTube
        if "googlevideo" in target_url and os.path.exists("cookies.txt"):
             cmd.extend(["--cookies", "cookies.txt"])
        else:
             cmd.extend(["--user-agent", MOBILE_UA])

        try:
            process = subprocess.Popen(cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=10**7)
            while True:
                chunk = process.stdout.read(64 * 1024)
                if not chunk: break
                yield chunk
            process.stdout.close()
            process.wait()
        except Exception as e:
            print(f"Stream Error: {e}")
    
    return StreamingResponse(
        iterfile(),
        media_type="application/octet-stream",
        headers=headers
    )

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
