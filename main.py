import os
import uvicorn
import yt_dlp
import requests
from bs4 import BeautifulSoup
from fastapi import FastAPI, HTTPException, Header, Depends, Query
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(title="Ultimate All-In-One", version="6.0.0")

app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"],
)

MASTER_KEY = "123Lock.on"
# Fake Browser Headers (Crucial for bypassing 403 errors)
USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'

class MediaRequest(BaseModel):
    url: str
    mode: str = "auto" # auto, video, audio, image

async def verify_api_key(x_api_key: str = Header(None)):
    if x_api_key != MASTER_KEY:
        raise HTTPException(status_code=403, detail="Access Denied")

# --- HELPER: Generic Image Scraper ---
def try_scrape_images(url):
    try:
        headers = {'User-Agent': USER_AGENT}
        res = requests.get(url, headers=headers, timeout=10)
        soup = BeautifulSoup(res.text, 'lxml')
        
        # Logic: Find the largest image (og:image) or first img tag
        img_url = None
        
        # 1. Try OpenGraph Image (Best for Shutterstock, Google, Articles)
        og_img = soup.find('meta', property='og:image')
        if og_img and og_img.get('content'):
            img_url = og_img['content']
        
        # 2. Fallback to Twitter Image
        if not img_url:
            tw_img = soup.find('meta', name='twitter:image')
            if tw_img and tw_img.get('content'):
                img_url = tw_img['content']
        
        if img_url:
            # Ensure full URL
            if img_url.startswith("//"): img_url = "https:" + img_url
            elif img_url.startswith("/"): img_url = url + img_url # Basic join
            
            return {
                "url": img_url,
                "title": soup.title.string if soup.title else "Image",
                "ext": "jpg"
            }
    except:
        return None
    return None

# --- MAIN EXTRACTION ENDPOINT ---
@app.post("/extract", dependencies=[Depends(verify_api_key)])
def extract_media(request: MediaRequest):
    url = request.url
    print(f"🔍 Analyzing: {url}")

    # 1. Try yt-dlp first (For Videos/Audio/TikTok/FB/YouTube)
    try:
        ydl_opts = {
            'quiet': True, 'no_warnings': True, 'noplaylist': True,
            'force_ipv4': True, 'nocheckcertificate': True,
            'user_agent': USER_AGENT,
            'format': 'best[ext=mp4]/best' if request.mode != 'audio' else 'bestaudio/best'
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            
            # Get Direct Link
            direct_url = info.get('url')
            # Fallback logic for complex sites
            if not direct_url and 'formats' in info:
                direct_url = info['formats'][-1]['url']

            return {
                "status": "success",
                "type": "video" if request.mode != "audio" else "audio",
                "title": info.get('title'),
                "thumbnail": info.get('thumbnail'),
                # Generate Proxy Link
                "download_url": f"/stream?target={direct_url}&title={info.get('title','file')}&key={MASTER_KEY}",
                "original_url": direct_url
            }

    except Exception as e:
        print(f"yt-dlp failed: {e}. Trying Image Scraper...")

    # 2. If Video failed, try Image Scraper (For Shutterstock, Google, etc)
    image_data = try_scrape_images(url)
    if image_data:
        return {
            "status": "success",
            "type": "image",
            "title": image_data['title'],
            "thumbnail": image_data['url'],
            # Proxy the image too
            "download_url": f"/stream?target={image_data['url']}&title=image&key={MASTER_KEY}"
        }

    raise HTTPException(status_code=404, detail="Could not find media on this page.")

# --- IMPROVED STREAMING (PROXY) ---
@app.get("/stream")
def stream_content(target: str = Query(...), title: str = Query("file"), key: str = Query(...)):
    if key != MASTER_KEY:
        raise HTTPException(status_code=403, detail="Invalid Key")

    try:
        # CRITICAL FIX: Send Headers so Source doesn't block us
        headers = {
            'User-Agent': USER_AGENT,
            'Referer': 'https://www.google.com/' # Fake referer helps
        }
        
        # Disable SSL verify to prevent cert errors on some sites
        # Stream = True is essential for RAM
        external_req = requests.get(target, headers=headers, stream=True, verify=False, timeout=15)
        
        # Detect Content Type (Video/Image/Audio)
        content_type = external_req.headers.get('content-type', 'application/octet-stream')
        
        # Clean Filename
        safe_title = "".join([c for c in title if c.isalnum() or c in " _-"])[:30]
        # Guess extension
        ext = "mp4"
        if "image" in content_type: ext = "jpg"
        if "audio" in content_type: ext = "mp3"
        
        filename = f"{safe_title}.{ext}"

        return StreamingResponse(
            external_req.iter_content(chunk_size=8192),
            media_type=content_type,
            headers={"Content-Disposition": f'attachment; filename="{filename}"'}
        )

    except Exception as e:
        print(f"Stream Error: {e}")
        raise HTTPException(status_code=500, detail="Source blocked the connection.")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
