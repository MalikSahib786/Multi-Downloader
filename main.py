import os
import uvicorn
import yt_dlp
import subprocess
import requests
from bs4 import BeautifulSoup
from urllib.parse import quote, unquote
from fastapi import FastAPI, HTTPException, Header, Depends, Query
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(title="Social Media API", version="AntiBot.3.0")

app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"],
)

MASTER_KEY = "123Lock.on"

# General Mobile UA for TikTok/Insta
MOBILE_UA = 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1'

class MediaRequest(BaseModel):
    url: str

async def verify_api_key(x_api_key: str = Header(None)):
    if x_api_key != MASTER_KEY:
        raise HTTPException(status_code=403, detail="Access Denied")

def format_size(bytes_size):
    if not bytes_size: return "Unknown Size"
    return f"{round(bytes_size / 1024 / 1024, 1)} MB"

def is_invalid_link(url):
    if "facebook.com/watch/" in url and "?v=" not in url and "videos/" not in url: return True
    if url.strip() == "https://www.youtube.com/" or url.strip() == "https://m.youtube.com/": return True
    return False

# --- SMART CONFIGURATION GENERATOR ---
def get_ydl_opts(url):
    # Base Options
    opts = {
        'quiet': True,
        'no_warnings': True,
        'noplaylist': True,
        'force_ipv4': True,
        'nocheckcertificate': True,
        'socket_timeout': 15,
    }

    # Check for cookies.txt in the server root (Optional advanced fix)
    if os.path.exists("cookies.txt"):
        opts['cookiefile'] = "cookies.txt"

    # YOUTUBE SPECIFIC CONFIG (The Bot Fix)
    if "youtube.com" in url or "youtu.be" in url:
        opts.update({
            # We do NOT set 'user_agent' here. We let yt-dlp use its internal Android client.
            'extractor_args': {
                'youtube': {
                    'player_client': ['android', 'ios'], # Pretend to be the App, not a Browser
                    'player_skip': ['webpage', 'configs', 'js'],
                    'include_ssr': False
                }
            }
        })
    # TIKTOK / OTHERS
    else:
        opts['user_agent'] = MOBILE_UA

    return opts

# --- FALLBACK SCRAPER ---
def try_social_image_scrape(url):
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}
        res = requests.get(url, headers=headers, timeout=10)
        soup = BeautifulSoup(res.text, 'html.parser')
        og_img = soup.find('meta', property='og:image')
        if og_img and og_img.get('content'):
            return {
                "status": "success",
                "title": soup.title.string or "Image",
                "thumbnail": og_img['content'],
                "source": "Image Scraper",
                "options": [{"type": "image", "label": "Download Image (HD)", "url": og_img['content'], "filesize": 0}]
            }
    except: pass
    return None

@app.post("/extract", dependencies=[Depends(verify_api_key)])
def extract_media(request: MediaRequest):
    raw_url = request.url
    url = raw_url.replace("x.com", "twitter.com")
    print(f"📱 Extracting: {url}")

    if is_invalid_link(url):
        raise HTTPException(status_code=400, detail="Please paste a specific VIDEO link.")

    try:
        # Get Smart Options based on URL type
        ydl_opts = get_ydl_opts(url)

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            
            video_options = {}
            audio_option = None
            
            formats = info.get('formats', [])
            duration = info.get('duration', 0)

            for f in formats:
                # AUDIO
                if f.get('vcodec') == 'none' and f.get('acodec') != 'none':
                    size = f.get('filesize') or f.get('filesize_approx') or 0
                    if not size and f.get('tbr') and duration: size = int((f.get('tbr') * 1024 * duration) / 8)
                    
                    audio_option = {
                        "type": "audio",
                        "label": f"Audio Only - {f.get('ext')} ({format_size(size)})",
                        "res_val": 0,
                        "url": f['url'],
                        "filesize": size
                    }

                # VIDEO
                elif f.get('vcodec') != 'none' and f.get('acodec') != 'none' and f.get('ext') == 'mp4':
                    height = f.get('height', 0)
                    if not height: continue
                    
                    size = f.get('filesize') or f.get('filesize_approx') or 0
                    if not size and f.get('tbr') and duration: size = int((f.get('tbr') * 1024 * duration) / 8)
                    
                    current_stored = video_options.get(height)
                    if not current_stored or size > current_stored['raw_size']:
                        video_options[height] = {
                            "type": "video",
                            "label": f"{height}p HD ({format_size(size)})",
                            "res_val": height,
                            "raw_size": size,
                            "url": f['url'],
                            "filesize": size
                        }

            final_options = list(video_options.values())
            final_options.sort(key=lambda x: x['res_val'], reverse=True)
            
            if audio_option: final_options.append(audio_option)

            # Fallback
            if not final_options:
                 direct_url = info.get('url')
                 if direct_url: 
                     final_options.append({"type": "video", "label": "Best Quality", "url": direct_url, "filesize": 0})

            return {
                "status": "success",
                "title": info.get('title') or "Video",
                "thumbnail": info.get('thumbnail'),
                "options": final_options
            }

    except Exception as e:
        print(f"yt-dlp error: {e}")
        image_data = try_social_image_scrape(url)
        if image_data: return image_data
        
        # Clean error message
        err_msg = str(e)
        if "Sign in" in err_msg:
            raise HTTPException(status_code=400, detail="Server IP blocked by YouTube. Cookies required.")
        
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
        
        # For Streaming, use Mobile UA if not YouTube
        # YouTube signed URLs usually prefer NO UA, or the one used to extract.
        # Since we extracted with Android Client, we let yt-dlp handle it natively.
        if "googlevideo" not in target_url:
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
