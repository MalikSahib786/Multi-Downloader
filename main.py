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

app = FastAPI(title="Social Media API", version="Final.Pro")

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

# --- HELPER: DETECT BAD LINKS ---
def is_invalid_link(url):
    # Facebook Watch Home
    if "facebook.com/watch/" in url and "?v=" not in url and "videos/" not in url:
        return True
    # YouTube Home
    if url.strip() == "https://www.youtube.com/" or url.strip() == "https://m.youtube.com/":
        return True
    return False

# --- FALLBACK FOR IMAGES (YouTube Posts / Insta Photos) ---
def try_social_image_scrape(url):
    print("⚠️ Attempting Fallback Scraper (Image Mode)...")
    try:
        headers = {'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'}
        res = requests.get(url, headers=headers, timeout=10)
        soup = BeautifulSoup(res.text, 'html.parser')
        
        # Look for OpenGraph Image
        og_img = soup.find('meta', property='og:image')
        if og_img and og_img.get('content'):
            title = soup.title.string if soup.title else "Social Media Image"
            return {
                "status": "success",
                "title": title,
                "thumbnail": og_img['content'],
                "source": "Image Scraper",
                "options": [{
                    "type": "image", 
                    "label": "Download Image (HD)", 
                    "url": og_img['content']
                }]
            }
    except Exception:
        pass
    return None

@app.post("/extract", dependencies=[Depends(verify_api_key)])
def extract_media(request: MediaRequest):
    url = request.url
    print(f"📱 Extracting: {url}")

    # 1. Validate Link
    if is_invalid_link(url):
        raise HTTPException(status_code=400, detail="Please paste a specific VIDEO link, not a Homepage/Profile.")

    # 2. Try yt-dlp (Video Mode)
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

                        if f_ext == 'mp4' and f.get('vcodec') != 'none':
                            formats_list.append({"type": "video", "label": f"{f_res} ({size_str})", "url": f['url']})
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
                "source": info.get('extractor_key'),
                "options": formats_list
            }

    except Exception as e:
        print(f"yt-dlp error: {e}")
        
        # 3. If Video failed, Try Image Fallback (For YouTube Community Posts)
        image_data = try_social_image_scrape(url)
        if image_data:
            return image_data
            
        # 4. Final Error
        raise HTTPException(status_code=400, detail="Could not find media. Link might be Private or Invalid.")

# --- NATIVE STREAMING (SUBPROCESS) ---
@app.get("/stream")
def stream_content(target: str = Query(...), title: str = Query("file"), key: str = Query(...)):
    if key != MASTER_KEY:
        raise HTTPException(status_code=403, detail="Invalid Key")

    target_url = unquote(target)
    print(f"☢️ Native Streaming: {target_url[:50]}...")

    # Detect File Type
    ext = "mp4"
    if ".jpg" in target_url or "yt3.ggpht" in target_url: ext = "jpg"
    elif ".mp3" in target_url or "audio" in title.lower(): ext = "mp3"
    
    safe_title = "".join([c for c in title if c.isalnum() or c in " _-"])[:50]
    filename = f"{safe_title}.{ext}"

    def iterfile():
        # yt-dlp streaming bypasses 403 blocks better than requests
        cmd = ["yt-dlp", "--no-part", "--quiet", "--no-warnings", "-o", "-", target_url]
        
        # Special Handling for YouTube Signed URLs
        if "googlevideo" in target_url:
            cmd.extend(["--user-agent", MOBILE_UA])

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
