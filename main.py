import os
import uvicorn
import yt_dlp
import subprocess
import requests
from bs4 import BeautifulSoup
from urllib.parse import quote, unquote
from functools import lru_cache
from fastapi import FastAPI, HTTPException, Header, Depends, Query
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(title="High-Speed Social API", version="Fast.Pro.1.0")

app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"],
)

MASTER_KEY = "123Lock.on"
# Mobile UA is faster and gets blocked less
MOBILE_UA = 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1'

class MediaRequest(BaseModel):
    url: str

async def verify_api_key(x_api_key: str = Header(None)):
    if x_api_key != MASTER_KEY:
        raise HTTPException(status_code=403, detail="Access Denied")

def format_size(bytes_size):
    if not bytes_size: return "Unknown"
    mb = bytes_size / 1024 / 1024
    return f"{round(mb, 1)} MB"

# --- SMART SIZE DETECTOR ---
def get_real_size(url, estimated_size=None):
    """
    Tries to get exact size via HTTP HEAD request.
    If that fails, returns the estimated size from yt-dlp.
    """
    try:
        # TikTok/Facebook/Twitter often allow HEAD requests
        headers = {'User-Agent': MOBILE_UA}
        if "tiktok.com" in url: headers['Referer'] = 'https://www.tiktok.com/'
        
        # Timeout must be short (1.5s) so we don't slow down the user
        response = requests.head(url, headers=headers, allow_redirects=True, timeout=1.5)
        
        if 'Content-Length' in response.headers:
            return int(response.headers['Content-Length'])
    except:
        pass
    
    return estimated_size

# --- CACHED EXTRACTOR (The Speed Booster) ---
# This remembers the last 50 results. If a user clicks "Download" again,
# or if two users check the same viral video, it loads instantly.
@lru_cache(maxsize=50)
def cached_extract_logic(url: str):
    print(f"⚡ Fetching fresh data for: {url}")
    
    # Twitter Fix
    if "x.com" in url: url = url.replace("x.com", "twitter.com")

    try:
        ydl_opts = {
            'quiet': True, 'no_warnings': True, 'noplaylist': True,
            'force_ipv4': True, 'nocheckcertificate': True,
            'user_agent': MOBILE_UA,
            'socket_timeout': 10, # Reduced timeout for speed
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            
            # -- RESOLUTION SORTING & SIZE CALCULATION --
            video_options = {}
            audio_option = None
            
            formats = info.get('formats', [])
            duration = info.get('duration', 0)

            for f in formats:
                # 1. AUDIO
                if f.get('vcodec') == 'none' and f.get('acodec') != 'none':
                    # Calculate Size
                    size = f.get('filesize') or f.get('filesize_approx')
                    if not size and f.get('tbr') and duration: size = (f.get('tbr') * 1024 * duration) / 8
                    
                    audio_option = {
                        "type": "audio",
                        "label": f"Audio Only ({format_size(size)})",
                        "res_val": 0,
                        "url": f['url']
                    }

                # 2. VIDEO (MP4)
                elif f.get('vcodec') != 'none' and f.get('acodec') != 'none' and f.get('ext') == 'mp4':
                    height = f.get('height', 0)
                    if not height: continue
                    
                    # Size Logic: Try yt-dlp data -> Math -> HEAD Request
                    size = f.get('filesize') or f.get('filesize_approx')
                    if not size and f.get('tbr') and duration: 
                        size = (f.get('tbr') * 1024 * duration) / 8
                    
                    # If we still don't have size, try the network ping (optional, can be slow)
                    # Uncomment next line if you want 100% accuracy but slightly slower speed
                    # if not size: size = get_real_size(f['url'], size)

                    current_stored = video_options.get(height)
                    if not current_stored or (size and current_stored['raw_size'] and size > current_stored['raw_size']):
                        video_options[height] = {
                            "type": "video",
                            "label": f"{height}p HD ({format_size(size)})",
                            "res_val": height,
                            "raw_size": size,
                            "url": f['url']
                        }

            final_options = list(video_options.values())
            final_options.sort(key=lambda x: x['res_val'], reverse=True)
            
            if audio_option: final_options.append(audio_option)

            # Fallback
            if not final_options:
                direct_url = info.get('url')
                if direct_url: 
                    final_options.append({"type": "video", "label": "Best Quality (Auto)", "url": direct_url})

            return {
                "status": "success",
                "title": info.get('title') or "Video",
                "thumbnail": info.get('thumbnail'),
                "source": info.get('extractor_key'),
                "options": final_options
            }

    except Exception as e:
        print(f"yt-dlp error: {e}")
        # Image Fallback
        return try_social_image_scrape(url)

def try_social_image_scrape(url):
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}
        res = requests.get(url, headers=headers, timeout=5) # Short timeout
        soup = BeautifulSoup(res.text, 'html.parser')
        og_img = soup.find('meta', property='og:image')
        if og_img and og_img.get('content'):
            return {
                "status": "success",
                "title": soup.title.string or "Image",
                "thumbnail": og_img['content'],
                "source": "Image Scraper",
                "options": [{"type": "image", "label": "Download Image (HD)", "url": og_img['content']}]
            }
    except: pass
    return None

@app.post("/extract", dependencies=[Depends(verify_api_key)])
def extract_media(request: MediaRequest):
    # Check cache first using the wrapper function
    result = cached_extract_logic(request.url)
    if result:
        return result
    raise HTTPException(status_code=400, detail="Could not find media. Private or Deleted?")

@app.get("/stream")
def stream_content(target: str = Query(...), title: str = Query("file"), key: str = Query(...)):
    if key != MASTER_KEY:
        raise HTTPException(status_code=403, detail="Invalid Key")

    target_url = unquote(target)
    print(f"☢️ Native Streaming: {target_url[:30]}...")

    # Filename & Extension Logic
    ext = "mp4"
    if ".jpg" in target_url or "yt3.ggpht" in target_url or "pbs.twimg" in target_url: ext = "jpg"
    elif ".mp3" in target_url or "audio" in title.lower(): ext = "mp3"
    
    try:
        ascii_title = title.encode('ascii', 'ignore').decode('ascii')
    except: ascii_title = "video"
    
    safe_title = "".join([c for c in ascii_title if c.isalnum() or c in " _-"])[:50]
    if not safe_title.strip(): safe_title = "media_file"
    
    filename = f"{safe_title}.{ext}"

    def iterfile():
        # Optimized Buffer Size (10MB) for faster start
        cmd = ["yt-dlp", "--no-part", "--quiet", "--no-warnings", "-o", "-", target_url]
        if "googlevideo" in target_url: cmd.extend(["--user-agent", MOBILE_UA])

        try:
            process = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, bufsize=10**7
            )
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
        headers={"Content-Disposition": f'attachment; filename="{filename}"'}
    )

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
