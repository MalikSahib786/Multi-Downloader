import os
import uvicorn
import yt_dlp
import requests
from urllib.parse import quote, urljoin
from bs4 import BeautifulSoup
from fastapi import FastAPI, HTTPException, Header, Depends, Query
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(title="Universal Media Downloader", version="8.0.0")

app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"],
)

MASTER_KEY = "123Lock.on"
USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'

class MediaRequest(BaseModel):
    url: str
    mode: str = "auto"

async def verify_api_key(x_api_key: str = Header(None)):
    if x_api_key != MASTER_KEY:
        raise HTTPException(status_code=403, detail="Access Denied")

# --- NEW: UNIVERSAL SCRAPER (Fallback for Pixabay, Pexels, etc) ---
def try_generic_scrape(url):
    """
    Scrapes any website for <video> or <img> tags if yt-dlp fails.
    """
    try:
        headers = {'User-Agent': USER_AGENT}
        res = requests.get(url, headers=headers, timeout=15)
        soup = BeautifulSoup(res.text, 'lxml')
        
        title = soup.title.string if soup.title else "Media File"
        
        # --- 1. Try Finding VIDEO ---
        video_url = None
        
        # A. Check OpenGraph Video
        og_vid = soup.find('meta', property='og:video')
        if og_vid and og_vid.get('content'): video_url = og_vid['content']
        
        # B. Check <video> tags
        if not video_url:
            vid_tag = soup.find('video')
            if vid_tag:
                if vid_tag.get('src'): 
                    video_url = vid_tag['src']
                else:
                    # Check <source> inside <video>
                    src_tag = vid_tag.find('source')
                    if src_tag and src_tag.get('src'):
                        video_url = src_tag['src']
        
        if video_url:
            # Fix relative URLs (e.g., /media/video.mp4 -> https://site.com/media/video.mp4)
            video_url = urljoin(url, video_url)
            return {"url": video_url, "title": title, "type": "video", "ext": "mp4"}

        # --- 2. Try Finding IMAGE ---
        img_url = None
        
        # A. Check OpenGraph Image
        og_img = soup.find('meta', property='og:image')
        if og_img and og_img.get('content'): img_url = og_img['content']
        
        # B. Check Twitter Image
        if not img_url:
            tw_img = soup.find('meta', name='twitter:image')
            if tw_img and tw_img.get('content'): img_url = tw_img['content']

        if img_url:
            img_url = urljoin(url, img_url)
            return {"url": img_url, "title": title, "type": "image", "ext": "jpg"}

    except Exception as e:
        print(f"Generic Scrape Error: {e}")
    
    return None

@app.post("/extract", dependencies=[Depends(verify_api_key)])
def extract_media(request: MediaRequest):
    url = request.url
    print(f"🔍 Analyzing: {url}")

    # STEP 1: Try yt-dlp (Best for YouTube, TikTok, FB, Insta)
    try:
        ydl_opts = {
            'quiet': True, 'no_warnings': True, 'noplaylist': True,
            'force_ipv4': True, 'nocheckcertificate': True,
            'user_agent': USER_AGENT,
            'format': 'best[ext=mp4]/best' if request.mode != 'audio' else 'bestaudio/best'
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            direct_url = info.get('url')
            
            # Fallback for complex manifests
            if not direct_url and 'formats' in info:
                direct_url = info['formats'][-1]['url']

            if direct_url:
                encoded_target = quote(direct_url)
                safe_title = quote(info.get('title', 'video'))
                
                return {
                    "status": "success",
                    "type": "video" if request.mode != "audio" else "audio",
                    "title": info.get('title'),
                    "thumbnail": info.get('thumbnail'),
                    "download_url": f"/stream?target={encoded_target}&title={safe_title}&key={MASTER_KEY}"
                }

    except Exception as e:
        print(f"yt-dlp skipped: {e}")

    # STEP 2: If yt-dlp failed, try Generic Scraper (Best for Pixabay, Pexels, News Sites)
    print("⚠️ yt-dlp failed, switching to Generic Scraper...")
    generic_data = try_generic_scrape(url)
    
    if generic_data:
        encoded_target = quote(generic_data['url'])
        safe_title = quote(generic_data['title'])
        
        return {
            "status": "success",
            "type": generic_data['type'],
            "title": generic_data['title'],
            "thumbnail": generic_data['url'] if generic_data['type'] == 'image' else "https://cdn-icons-png.flaticon.com/512/238/238034.png",
            "download_url": f"/stream?target={encoded_target}&title={safe_title}&key={MASTER_KEY}"
        }

    raise HTTPException(status_code=404, detail="Could not find any media on this page.")

@app.get("/stream")
def stream_content(target: str = Query(...), title: str = Query("file"), key: str = Query(...)):
    if key != MASTER_KEY:
        raise HTTPException(status_code=403, detail="Invalid Key")

    try:
        headers = {'User-Agent': USER_AGENT}
        # Stream = True saves RAM
        external_req = requests.get(target, headers=headers, stream=True, verify=False, timeout=20)
        
        if external_req.status_code >= 400:
            raise HTTPException(status_code=400, detail="Target link expired or blocked")

        content_type = external_req.headers.get('content-type', 'application/octet-stream')
        
        # Guess extension based on content-type if possible, else default to mp4/jpg
        ext = "mp4"
        if "image" in content_type: ext = "jpg"
        if "audio" in content_type: ext = "mp3"
        
        filename = f"{title}.{ext}"

        return StreamingResponse(
            external_req.iter_content(chunk_size=8192),
            media_type=content_type,
            headers={"Content-Disposition": f'attachment; filename="{filename}"'}
        )

    except Exception as e:
        print(f"Stream Error: {e}")
        raise HTTPException(status_code=500, detail="Stream Connection Failed")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
