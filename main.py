import os
import uvicorn
import yt_dlp
import requests
import json
from urllib.parse import quote, unquote
from bs4 import BeautifulSoup
from fastapi import FastAPI, HTTPException, Header, Depends, Query
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(title="Ultimate Media API", version="9.0.0")

app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"],
)

MASTER_KEY = "123Lock.on"
USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'

class MediaRequest(BaseModel):
    url: str

async def verify_api_key(x_api_key: str = Header(None)):
    if x_api_key != MASTER_KEY:
        raise HTTPException(status_code=403, detail="Access Denied")

# --- NEW: JSON-LD SCRAPER (Fixes Pixabay, Pexels, Instagram) ---
def try_json_ld_scrape(url):
    try:
        headers = {'User-Agent': USER_AGENT}
        res = requests.get(url, headers=headers, timeout=15)
        soup = BeautifulSoup(res.text, 'lxml')
        
        # 1. Look for JSON-LD script tags
        scripts = soup.find_all('script', type='application/ld+json')
        for script in scripts:
            try:
                data = json.loads(script.string)
                # Pixabay/Pexels structure often has "contentUrl" or "video"
                if isinstance(data, list): data = data[0] # Sometimes it's a list
                
                video_url = data.get('contentUrl') or data.get('embedUrl')
                
                # Deep check for nested objects (common in Schema.org)
                if not video_url and 'video' in data:
                    video_url = data['video'].get('contentUrl')
                
                if video_url:
                    title = data.get('name') or data.get('headline') or soup.title.string
                    return {
                        "url": video_url,
                        "title": title,
                        "resolution": "HD (Stock)",
                        "filesize": "Unknown"
                    }
            except:
                continue
                
        # 2. Fallback to standard meta tags
        og_vid = soup.find('meta', property='og:video')
        if og_vid:
            return {
                "url": og_vid['content'],
                "title": soup.title.string,
                "resolution": "Standard",
                "filesize": "Unknown"
            }
            
    except Exception as e:
        print(f"Scrape Error: {e}")
    return None

@app.post("/extract", dependencies=[Depends(verify_api_key)])
def extract_media(request: MediaRequest):
    url = request.url
    print(f"🔍 Processing: {url}")

    # STEP 1: Try yt-dlp (YouTube, TikTok, FB)
    try:
        ydl_opts = {
            'quiet': True, 'no_warnings': True, 'noplaylist': True,
            'force_ipv4': True, 'nocheckcertificate': True,
            'user_agent': USER_AGENT,
        }

        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            
            formats_list = []
            
            # LOGIC: Extract different qualities
            # We look for MP4s with both Audio and Video
            if 'formats' in info:
                for f in info['formats']:
                    # Filter for mp4 video+audio or good quality audio
                    if f.get('url'):
                        f_ext = f.get('ext')
                        f_note = f.get('format_note', 'Standard')
                        f_res = f.get('resolution') or f"{f.get('height')}p"
                        
                        # Calculate Filesize
                        size = f.get('filesize') or f.get('filesize_approx')
                        size_str = f"{round(size / 1024 / 1024, 1)} MB" if size else "Unknown Size"

                        # 1. Video with Audio (The Best Ones)
                        if f_ext == 'mp4' and f.get('vcodec') != 'none' and f.get('acodec') != 'none':
                            formats_list.append({
                                "type": "video",
                                "label": f"Video MP4 - {f_res} ({size_str})",
                                "url": f['url']
                            })
                        
                        # 2. Audio Only
                        elif f.get('vcodec') == 'none' and f.get('acodec') != 'none':
                             formats_list.append({
                                "type": "audio",
                                "label": f"Audio Only - {f_ext} ({size_str})",
                                "url": f['url']
                            })

            # If no formats found (TikTok often has just one 'url'), use main info
            if not formats_list:
                 direct_url = info.get('url')
                 if direct_url:
                     formats_list.append({
                         "type": "video",
                         "label": "Best Quality (Auto)",
                         "url": direct_url
                     })

            # Reverse to show Best Quality first
            formats_list.reverse()

            # Prepare Response
            return {
                "status": "success",
                "title": info.get('title'),
                "thumbnail": info.get('thumbnail'),
                "source": "yt-dlp",
                "options": formats_list
            }

    except Exception as e:
        print(f"yt-dlp failed: {e}. Trying JSON-LD...")

    # STEP 2: Pixabay/Pexels/Generic Fallback
    scrape_data = try_json_ld_scrape(url)
    if scrape_data:
        return {
            "status": "success",
            "title": scrape_data['title'],
            "thumbnail": "https://cdn-icons-png.flaticon.com/512/8002/8002111.png",
            "source": "scraper",
            "options": [{
                "type": "video",
                "label": f"Download File ({scrape_data['resolution']})",
                "url": scrape_data['url']
            }]
        }

    raise HTTPException(status_code=404, detail="Could not find media on this page.")

# --- STREAMING ENDPOINT (The Fix for TikTok/Pixabay) ---
@app.get("/stream")
def stream_content(target: str = Query(...), title: str = Query("file"), key: str = Query(...)):
    if key != MASTER_KEY:
        raise HTTPException(status_code=403, detail="Invalid Key")

    try:
        # Decode URL if it was encoded by frontend
        target_url = unquote(target)
        
        # HEADERS HACK: Fixes TikTok "Stream Connection Failed"
        # TikTok requires the Referer to be tiktok.com
        headers = {
            'User-Agent': USER_AGENT,
            'Referer': 'https://www.tiktok.com/',
            'Range': 'bytes=0-' # Asks for the whole file
        }
        
        # 30 Second Timeout + SSL Verify False
        external_req = requests.get(target_url, headers=headers, stream=True, verify=False, timeout=30)
        
        if external_req.status_code >= 400:
            # Try one more time without headers (sometimes Pixabay hates headers)
            external_req = requests.get(target_url, stream=True, verify=False, timeout=30)
            if external_req.status_code >= 400:
                print(f"Source returned: {external_req.status_code}")
                raise HTTPException(status_code=400, detail="Link Blocked by Source")

        content_type = external_req.headers.get('content-type', 'application/octet-stream')
        
        # Clean Title
        safe_title = "".join([c for c in title if c.isalnum() or c in " _-"])[:40]
        ext = "mp4"
        if "audio" in content_type: ext = "mp3"
        if "image" in content_type: ext = "jpg"
        
        filename = f"{safe_title}.{ext}"

        return StreamingResponse(
            external_req.iter_content(chunk_size=64*1024), # 64KB Chunks
            media_type=content_type,
            headers={"Content-Disposition": f'attachment; filename="{filename}"'}
        )

    except Exception as e:
        print(f"Stream Error: {e}")
        raise HTTPException(status_code=500, detail="Stream Failed")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
