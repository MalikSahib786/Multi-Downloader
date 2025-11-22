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

app = FastAPI(title="Social Media API", version="TwitterFix.1.0")

app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"],
)

MASTER_KEY = "123Lock.on"

# --- USER AGENTS ---
# Mobile UA (Best for TikTok/Instagram/FB)
MOBILE_UA = 'Mozilla/5.0 (iPhone; CPU iPhone OS 16_6 like Mac OS X) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/16.6 Mobile/15E148 Safari/604.1'
# Desktop UA (Best for Twitter/X to get MP4 instead of M3U8)
DESKTOP_UA = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'

class MediaRequest(BaseModel):
    url: str

async def verify_api_key(x_api_key: str = Header(None)):
    if x_api_key != MASTER_KEY:
        raise HTTPException(status_code=403, detail="Access Denied")

def format_size(bytes_size):
    if not bytes_size: return "Unknown Size"
    return f"{round(bytes_size / 1024 / 1024, 1)} MB"

def fix_twitter_url(url):
    # yt-dlp sometimes prefers twitter.com over x.com
    if "x.com" in url:
        return url.replace("x.com", "twitter.com")
    return url

# --- FALLBACK SCRAPER ---
def try_social_image_scrape(url):
    try:
        headers = {'User-Agent': DESKTOP_UA}
        res = requests.get(url, headers=headers, timeout=10)
        soup = BeautifulSoup(res.text, 'html.parser')
        og_img = soup.find('meta', property='og:image')
        if og_img and og_img.get('content'):
            return {
                "status": "success",
                "title": soup.title.string or "Image",
                "thumbnail": og_img['content'],
                "source": "Image Scraper",
                "options": [{"type": "image", "label": "Download Image", "url": og_img['content']}]
            }
    except: pass
    return None

@app.post("/extract", dependencies=[Depends(verify_api_key)])
def extract_media(request: MediaRequest):
    raw_url = request.url
    url = fix_twitter_url(raw_url)
    print(f"📱 Extracting: {url}")

    # DETECT TWITTER/X
    is_twitter = "twitter.com" in url or "x.com" in url
    
    # SELECT USER AGENT
    # Twitter needs Desktop UA to provide MP4 files.
    # TikTok/FB needs Mobile UA to avoid login pages.
    current_ua = DESKTOP_UA if is_twitter else MOBILE_UA

    try:
        ydl_opts = {
            'quiet': True, 'no_warnings': True, 'noplaylist': True,
            'force_ipv4': True, 'nocheckcertificate': True,
            'user_agent': current_ua, # Dynamic User Agent
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

                        # MP4 Video (Ignore m3u8 for Twitter)
                        if f_ext == 'mp4' and f.get('vcodec') != 'none':
                            if is_twitter and "m3u8" in f['url']: continue # Skip HLS on Twitter
                            
                            formats_list.append({"type": "video", "label": f"{f_res} ({size_str})", "url": f['url']})
                        
                        # Audio
                        elif f.get('vcodec') == 'none' and f.get('acodec') != 'none':
                             formats_list.append({"type": "audio", "label": f"Audio - {f_ext}", "url": f['url']})

            if not formats_list:
                 direct_url = info.get('url')
                 if direct_url: formats_list.append({"type": "video", "label": "Best Quality", "url": direct_url})

            formats_list.reverse()

            return {
                "status": "success",
                "title": info.get('title') or "Social Video",
                "thumbnail": info.get('thumbnail'),
                "source": info.get('extractor_key'),
                "options": formats_list
            }

    except Exception as e:
        print(f"yt-dlp error: {e}")
        img_data = try_social_image_scrape(url)
        if img_data: return img_data
        raise HTTPException(status_code=400, detail="Could not process link.")

# --- NATIVE STREAMING ---
@app.get("/stream")
def stream_content(target: str = Query(...), title: str = Query("file"), key: str = Query(...)):
    if key != MASTER_KEY:
        raise HTTPException(status_code=403, detail="Invalid Key")

    target_url = unquote(target)
    
    # Fix Filename Extension
    ext = "mp4"
    if ".jpg" in target_url or "yt3.ggpht" in target_url or "pbs.twimg.com" in target_url: ext = "jpg"
    elif ".mp3" in target_url: ext = "mp3"
    
    safe_title = "".join([c for c in title if c.isalnum() or c in " _-"])[:50]
    filename = f"{safe_title}.{ext}"

    def iterfile():
        # yt-dlp to stdout is the most reliable way
        cmd = ["yt-dlp", "--no-part", "--quiet", "--no-warnings", "-o", "-", target_url]
        
        # Twitter/X often needs Desktop UA to allow the download
        if "twimg.com" in target_url or "twitter" in target_url:
             cmd.extend(["--user-agent", DESKTOP_UA])
        elif "googlevideo" in target_url:
             cmd.extend(["--user-agent", MOBILE_UA])

        try:
            # 10MB Buffer prevents stuttering
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
