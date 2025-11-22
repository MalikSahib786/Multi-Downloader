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

app = FastAPI(title="Ultimate Media API", version="10.0.0")

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

# --- HELPER: FORMAT SIZE ---
def format_size(bytes_size):
    if not bytes_size: return "Unknown Size"
    return f"{round(bytes_size / 1024 / 1024, 1)} MB"

# --- HELPER: JSON-LD SCRAPER ---
def try_json_ld_scrape(url):
    try:
        headers = {'User-Agent': USER_AGENT}
        res = requests.get(url, headers=headers, timeout=15)
        soup = BeautifulSoup(res.text, 'lxml')
        
        # Pixabay/Pexels JSON Logic
        scripts = soup.find_all('script', type='application/ld+json')
        for script in scripts:
            try:
                data = json.loads(script.string)
                if isinstance(data, list): data = data[0]
                
                video_url = data.get('contentUrl') or data.get('embedUrl')
                if not video_url and 'video' in data:
                    video_url = data['video'].get('contentUrl')
                
                if video_url:
                    return {
                        "url": video_url,
                        "title": data.get('name') or soup.title.string,
                        "resolution": "HD Stock",
                        "filesize": "Unknown Size"
                    }
            except:
                continue
    except Exception:
        pass
    return None

@app.post("/extract", dependencies=[Depends(verify_api_key)])
def extract_media(request: MediaRequest):
    url = request.url
    print(f"🔍 Processing: {url}")

    # STEP 1: Try yt-dlp
    try:
        ydl_opts = {
            'quiet': True, 'no_warnings': True, 'noplaylist': True,
            'force_ipv4': True, 'nocheckcertificate': True,
            'user_agent': USER_AGENT,
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
                        
                        # --- FIX: CALCULATE SIZE IF MISSING ---
                        size = f.get('filesize') or f.get('filesize_approx')
                        if not size and f.get('tbr') and duration:
                            # Estimate: (Bitrate * Duration) / 8
                            size = (f.get('tbr') * 1024 * duration) / 8
                        
                        size_str = format_size(size)

                        # 1. Best Video with Audio
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

            if not formats_list:
                 direct_url = info.get('url')
                 if direct_url:
                     formats_list.append({
                         "type": "video",
                         "label": "Best Quality (Auto)",
                         "url": direct_url
                     })

            formats_list.reverse()

            return {
                "status": "success",
                "title": info.get('title'),
                "thumbnail": info.get('thumbnail'),
                "options": formats_list
            }

    except Exception as e:
        print(f"yt-dlp failed: {e}")

    # STEP 2: Generic Scraper Fallback
    scrape_data = try_json_ld_scrape(url)
    if scrape_data:
        return {
            "status": "success",
            "title": scrape_data['title'],
            "thumbnail": "https://cdn-icons-png.flaticon.com/512/8002/8002111.png",
            "options": [{
                "type": "video",
                "label": f"Download File ({scrape_data['resolution']})",
                "url": scrape_data['url']
            }]
        }

    raise HTTPException(status_code=404, detail="Could not find media on this page.")

# --- STREAMING ENDPOINT (FIXED) ---
@app.get("/stream")
def stream_content(target: str = Query(...), title: str = Query("file"), key: str = Query(...)):
    if key != MASTER_KEY:
        raise HTTPException(status_code=403, detail="Invalid Key")

    try:
        target_url = unquote(target)
        
        # --- SMART HEADERS ---
        headers = {'User-Agent': USER_AGENT}
        
        # If TikTok: Needs Referer
        if "tiktok.com" in target_url or "akamaized" in target_url:
            headers['Referer'] = 'https://www.tiktok.com/'
            
        # If YouTube: Needs CLEAN headers (No Referer, sometimes No User-Agent)
        # YouTube links are signed, sending wrong headers breaks the signature.
        elif "googlevideo.com" in target_url:
             headers = {} # Send empty headers for YouTube signed URLs

        external_req = requests.get(target_url, headers=headers, stream=True, verify=False, timeout=30)
        
        # Retrying for weird servers
        if external_req.status_code >= 400:
             # Try again with no headers at all
             external_req = requests.get(target_url, stream=True, verify=False, timeout=30)
             
        if external_req.status_code >= 400:
            print(f"Stream Error Code: {external_req.status_code}")
            raise HTTPException(status_code=400, detail=f"Source Blocked: {external_req.status_code}")

        content_type = external_req.headers.get('content-type', 'application/octet-stream')
        safe_title = "".join([c for c in title if c.isalnum() or c in " _-"])[:40]
        
        ext = "mp4"
        if "audio" in content_type: ext = "mp3"
        if "image" in content_type: ext = "jpg"
        
        filename = f"{safe_title}.{ext}"

        return StreamingResponse(
            external_req.iter_content(chunk_size=64*1024),
            media_type=content_type,
            headers={"Content-Disposition": f'attachment; filename="{filename}"'}
        )

    except Exception as e:
        print(f"Stream Exception: {e}")
        raise HTTPException(status_code=500, detail="Stream Failed")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
