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

app = FastAPI(title="Ultimate Media API", version="12.0.0")

app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"],
)

MASTER_KEY = "123Lock.on"

# Standard Browser
USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36'

class MediaRequest(BaseModel):
    url: str

async def verify_api_key(x_api_key: str = Header(None)):
    if x_api_key != MASTER_KEY:
        raise HTTPException(status_code=403, detail="Access Denied")

def format_size(bytes_size):
    if not bytes_size: return "Unknown Size"
    return f"{round(bytes_size / 1024 / 1024, 1)} MB"

# --- ADVANCED SCRAPER (Handles Canva, YouTube Posts, etc) ---
def try_advanced_scrape(url):
    try:
        headers = {'User-Agent': USER_AGENT}
        # Verify=False helps with older SSL sites
        res = requests.get(url, headers=headers, timeout=15, verify=False)
        soup = BeautifulSoup(res.text, 'lxml')
        
        title = soup.title.string if soup.title else "Media File"
        image_url = None
        video_url = None

        # 1. Check JSON-LD (Best for Pexels/Pixabay)
        scripts = soup.find_all('script', type='application/ld+json')
        for script in scripts:
            try:
                data = json.loads(script.string)
                if isinstance(data, list): data = data[0]
                
                # Video check
                v = data.get('contentUrl') or data.get('embedUrl')
                if not v and 'video' in data: v = data['video'].get('contentUrl')
                if v: 
                    return {"url": v, "title": title, "type": "video", "label": "HD Stock Video"}

                # Image check
                i = data.get('image')
                if i:
                    if isinstance(i, dict): i = i.get('url')
                    if i: return {"url": i, "title": title, "type": "image", "label": "High Res Image"}
            except: continue

        # 2. Check OpenGraph (Best for Canva, YouTube Posts)
        # YouTube Posts put the image in og:image
        og_img = soup.find('meta', property='og:image')
        if og_img and og_img.get('content'): 
            image_url = og_img['content']
        
        og_vid = soup.find('meta', property='og:video')
        if og_vid and og_vid.get('content'): 
            video_url = og_vid['content']

        # 3. Fallback: Twitter Card
        if not image_url:
            tw_img = soup.find('meta', name='twitter:image')
            if tw_img: image_url = tw_img.get('content')

        # 4. Fallback: Link rel=image_src (Old YouTube)
        if not image_url:
            link_img = soup.find('link', rel='image_src')
            if link_img: image_url = link_img.get('href')

        # RETURN RESULTS
        if video_url:
            return {"url": video_url, "title": title, "type": "video", "label": "Detected Video"}
        
        if image_url:
            return {"url": image_url, "title": title, "type": "image", "label": "Detected Image/Preview"}

    except Exception as e:
        print(f"Scrape Failed: {e}")
    return None

@app.post("/extract", dependencies=[Depends(verify_api_key)])
def extract_media(request: MediaRequest):
    url = request.url
    print(f"🔍 Processing: {url}")

    # STEP 1: Try yt-dlp (Video Platforms)
    # We skip yt-dlp for Canva because it takes too long and fails
    if "canva.com" not in url:
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
                            
                            size = f.get('filesize') or f.get('filesize_approx')
                            if not size and f.get('tbr') and duration:
                                size = (f.get('tbr') * 1024 * duration) / 8
                            
                            size_str = format_size(size)

                            if f_ext == 'mp4' and f.get('vcodec') != 'none' and f.get('acodec') != 'none':
                                formats_list.append({"type": "video", "label": f"Video MP4 - {f_res} ({size_str})", "url": f['url']})
                            elif f.get('vcodec') == 'none' and f.get('acodec') != 'none':
                                formats_list.append({"type": "audio", "label": f"Audio Only - {f_ext}", "url": f['url']})

                if not formats_list:
                    direct = info.get('url')
                    if direct: formats_list.append({"type": "video", "label": "Best Quality", "url": direct})

                if formats_list:
                    formats_list.reverse()
                    return {
                        "status": "success",
                        "title": info.get('title'),
                        "thumbnail": info.get('thumbnail'),
                        "options": formats_list
                    }

        except Exception as e:
            print(f"yt-dlp skipped: {e}")

    # STEP 2: Advanced Scraper (Canva, YouTube Posts, Stock Sites)
    scrape_data = try_advanced_scrape(url)
    if scrape_data:
        return {
            "status": "success",
            "title": scrape_data['title'],
            "thumbnail": scrape_data['url'], # The image IS the thumbnail
            "options": [{
                "type": scrape_data['type'],
                "label": scrape_data['label'],
                "url": scrape_data['url']
            }]
        }

    raise HTTPException(status_code=404, detail="Could not find compatible media.")

# --- RETRY STREAMING ENDPOINT ---
@app.get("/stream")
def stream_content(target: str = Query(...), title: str = Query("file"), key: str = Query(...)):
    if key != MASTER_KEY:
        raise HTTPException(status_code=403, detail="Invalid Key")

    try:
        target_url = unquote(target)
        
        # STRATEGY 1: Standard Headers
        headers = {'User-Agent': USER_AGENT}
        
        if "tiktok.com" in target_url or "akamaized" in target_url:
            headers['Referer'] = 'https://www.tiktok.com/'
        elif "googlevideo.com" in target_url:
            if 'Referer' in headers: del headers['Referer']

        external_req = requests.get(target_url, headers=headers, stream=True, verify=False, timeout=20)
        
        # STRATEGY 2: Retry with NO headers (Fixes 403 on some CDNs)
        if external_req.status_code >= 400:
            print(f"Strategy 1 failed ({external_req.status_code}). Trying Strategy 2 (No Headers)...")
            external_req = requests.get(target_url, stream=True, verify=False, timeout=20)
            
        # STRATEGY 3: Retry with Wget User Agent (Rare fix)
        if external_req.status_code >= 400:
            print(f"Strategy 2 failed. Trying Strategy 3 (Wget)...")
            h3 = {'User-Agent': 'Wget/1.21.4'}
            external_req = requests.get(target_url, headers=h3, stream=True, verify=False, timeout=20)

        # FINAL CHECK
        if external_req.status_code >= 400:
            raise HTTPException(status_code=400, detail=f"Source blocked download: {external_req.status_code}")

        content_type = external_req.headers.get('content-type', 'application/octet-stream')
        safe_title = "".join([c for c in title if c.isalnum() or c in " _-"])[:40]
        
        ext = "mp4"
        if "image" in content_type: ext = "jpg"
        if "audio" in content_type: ext = "mp3"
        
        filename = f"{safe_title}.{ext}"

        return StreamingResponse(
            external_req.iter_content(chunk_size=64*1024),
            media_type=content_type,
            headers={"Content-Disposition": f'attachment; filename="{filename}"'}
        )

    except Exception as e:
        print(f"Stream Error: {e}")
        raise HTTPException(status_code=500, detail="Stream Connection Failed")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
