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

app = FastAPI(title="Universal Media API", version="Hybrid.Pro")

app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"],
)

MASTER_KEY = "123Lock.on"

# AGENTS
MOBILE_UA = 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1'
DESKTOP_UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'

class MediaRequest(BaseModel):
    url: str

async def verify_api_key(x_api_key: str = Header(None)):
    if x_api_key != MASTER_KEY:
        raise HTTPException(status_code=403, detail="Access Denied")

def format_size(bytes_size):
    if not bytes_size: return "Unknown"
    return f"{round(bytes_size / 1024 / 1024, 1)} MB"

def is_invalid_link(url):
    if "facebook.com/watch/" in url and "?v=" not in url and "videos/" not in url: return True
    return False

# --- ENGINE B: IMAGE SCRAPER (Fallback) ---
def try_image_scrape(url):
    print("⚠️ Video failed. Switching to Image Scraper...")
    try:
        # Use Desktop UA for better meta tag scraping
        headers = {'User-Agent': DESKTOP_UA}
        res = requests.get(url, headers=headers, timeout=10)
        soup = BeautifulSoup(res.text, 'html.parser')
        
        image_url = None
        
        # 1. OpenGraph Image (Insta, FB, Medium, etc)
        og_img = soup.find('meta', property='og:image')
        if og_img: image_url = og_img.get('content')
        
        # 2. Twitter Image
        if not image_url:
            tw_img = soup.find('meta', name='twitter:image')
            if tw_img: image_url = tw_img.get('content')
            
        # 3. Link Rel Image
        if not image_url:
            link_img = soup.find('link', rel='image_src')
            if link_img: image_url = link_img.get('href')

        if image_url:
            title = soup.title.string if soup.title else "Social Media Image"
            return {
                "status": "success",
                "title": title,
                "thumbnail": image_url,
                "source": "Image Scraper",
                "options": [{
                    "type": "image", 
                    "label": "Download Image (HD)", 
                    "url": image_url,
                    "filesize": 0
                }]
            }
    except Exception as e:
        print(f"Scraper Error: {e}")
    return None

@app.post("/extract", dependencies=[Depends(verify_api_key)])
def extract_media(request: MediaRequest):
    raw_url = request.url
    url = raw_url.replace("x.com", "twitter.com") # Fix X links
    print(f"📱 Extracting: {url}")

    if is_invalid_link(url):
        raise HTTPException(status_code=400, detail="Invalid Link")

    # --- ENGINE A: VIDEO EXTRACTOR (yt-dlp) ---
    try:
        ydl_opts = {
            'quiet': True,
            'no_warnings': True,
            'noplaylist': True,
            'force_ipv4': True,
            'nocheckcertificate': True,
            'socket_timeout': 15,
            'user_agent': MOBILE_UA,
        }

        # YouTube Bot Bypass
        if "youtube.com" in url or "youtu.be" in url:
             ydl_opts['extractor_args'] = {
                'youtube': {
                    'player_client': ['android', 'web'],
                    'player_skip': ['webpage', 'configs', 'js'],
                    'include_ssr': False
                }
            }

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

            if not final_options:
                 direct_url = info.get('url')
                 if direct_url: 
                     final_options.append({"type": "video", "label": "Best Quality", "url": direct_url, "filesize": 0})

            return {
                "status": "success",
                "title": info.get('title'),
                "thumbnail": info.get('thumbnail'),
                "options": final_options
            }

    except Exception as e:
        print(f"yt-dlp Error: {e}")
        
        # --- ENGINE B: FALLBACK TO IMAGE SCRAPER ---
        # If yt-dlp fails, we assume it might be an Image Post (Insta Photo, Tweet)
        image_data = try_image_scrape(url)
        if image_data:
            return image_data

        # If both fail, show error
        if "Sign in" in str(e):
             raise HTTPException(status_code=400, detail="YouTube blocked this IP. Try again later.")
        raise HTTPException(status_code=400, detail="Could not find media. Link might be private.")

@app.get("/stream")
def stream_content(target: str = Query(...), title: str = Query("file"), size: int = Query(None), key: str = Query(...)):
    if key != MASTER_KEY:
        raise HTTPException(status_code=403, detail="Invalid Key")

    target_url = unquote(target)
    print(f"☢️ Streaming: {target_url[:40]}...")

    # Smart Extension
    ext = "mp4"
    if ".jpg" in target_url or "yt3.ggpht" in target_url or "instagram" in target_url and ".jpg" in target_url: 
        ext = "jpg"
    elif ".png" in target_url: 
        ext = "png"
    elif ".mp3" in target_url or "audio" in title.lower(): 
        ext = "mp3"
    
    # ASCII Filename Fix
    try:
        ascii_title = title.encode('ascii', 'ignore').decode('ascii')
    except: ascii_title = "media"
    safe_title = "".join([c for c in ascii_title if c.isalnum() or c in " _-"])[:50]
    if not safe_title: safe_title = "download"
    filename = f"{safe_title}.{ext}"

    # Headers
    headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
    # Only send content-length if we are 100% sure (prevents Protocol Error)
    if size and size > 0: 
        headers["Content-Length"] = str(size)

    def iterfile():
        # yt-dlp streaming is safest for videos
        # For images, we could use requests, but yt-dlp works too
        cmd = ["yt-dlp", "--force-ipv4", "--no-part", "--quiet", "--no-warnings", "-o", "-", target_url]
        if "googlevideo" in target_url: cmd.extend(["--user-agent", MOBILE_UA])

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
