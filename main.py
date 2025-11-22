import os
import uvicorn
import yt_dlp
import requests
import json
import urllib3
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry
from urllib.parse import quote, unquote
from bs4 import BeautifulSoup
from fastapi import FastAPI, HTTPException, Header, Depends, Query
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# Disable SSL Warnings (We verify=False to allow all downloads)
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

app = FastAPI(title="Ultimate Media API", version="13.0.0")

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

def format_size(bytes_size):
    if not bytes_size: return "Unknown Size"
    return f"{round(bytes_size / 1024 / 1024, 1)} MB"

# --- ROBUST NETWORK SESSION (The Fix for Connection Failed) ---
def get_robust_session():
    session = requests.Session()
    # Retry 3 times on connection errors, status 500, 502, 503, 504
    retry_strategy = Retry(
        total=3,
        backoff_factor=1, # Wait 1s, then 2s, then 4s
        status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=["HEAD", "GET", "OPTIONS"]
    )
    adapter = HTTPAdapter(max_retries=retry_strategy)
    session.mount("https://", adapter)
    session.mount("http://", adapter)
    return session

# --- SCRAPER LOGIC ---
def try_advanced_scrape(url):
    try:
        session = get_robust_session()
        headers = {'User-Agent': USER_AGENT}
        res = session.get(url, headers=headers, timeout=15, verify=False)
        soup = BeautifulSoup(res.text, 'lxml')
        
        title = soup.title.string if soup.title else "Media File"
        
        # JSON-LD Check
        scripts = soup.find_all('script', type='application/ld+json')
        for script in scripts:
            try:
                data = json.loads(script.string)
                if isinstance(data, list): data = data[0]
                
                v = data.get('contentUrl') or data.get('embedUrl')
                if not v and 'video' in data: v = data['video'].get('contentUrl')
                if v: return {"url": v, "title": title, "type": "video", "label": "HD Stock Video"}
                
                i = data.get('image')
                if i:
                    if isinstance(i, dict): i = i.get('url')
                    if i: return {"url": i, "title": title, "type": "image", "label": "High Res Image"}
            except: continue

        # Meta Tags Check
        og_img = soup.find('meta', property='og:image')
        if og_img: return {"url": og_img['content'], "title": title, "type": "image", "label": "Preview Image"}

    except Exception as e:
        print(f"Scrape Failed: {e}")
    return None

@app.post("/extract", dependencies=[Depends(verify_api_key)])
def extract_media(request: MediaRequest):
    url = request.url
    print(f"🔍 Processing: {url}")

    # Skip yt-dlp for Canva/Posts
    if "canva.com" not in url and "pinterest" not in url:
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

    scrape_data = try_advanced_scrape(url)
    if scrape_data:
        return {
            "status": "success",
            "title": scrape_data['title'],
            "thumbnail": scrape_data['url'],
            "options": [{"type": scrape_data['type'], "label": scrape_data['label'], "url": scrape_data['url']}]
        }

    raise HTTPException(status_code=404, detail="Could not find media.")

# --- THE PROFESSIONAL STREAMING ENDPOINT ---
@app.get("/stream")
def stream_content(target: str = Query(...), title: str = Query("file"), key: str = Query(...)):
    if key != MASTER_KEY:
        raise HTTPException(status_code=403, detail="Invalid Key")

    try:
        target_url = unquote(target)
        session = get_robust_session() # Use the robust session
        
        # Strategy 1: Identity Headers
        headers = {'User-Agent': USER_AGENT}
        if "tiktok.com" in target_url or "akamaized" in target_url:
            headers['Referer'] = 'https://www.tiktok.com/'
        elif "googlevideo.com" in target_url:
            headers = {} # Send NO headers for YouTube (Works best for signed URLs)

        # Connect (Stream=True, Verify=False)
        # Timeout=(ConnectionTimeout, ReadTimeout) -> (10s to connect, 60s to read)
        external_req = session.get(target_url, headers=headers, stream=True, verify=False, timeout=(10, 60))

        # Strategy 2: Retry Without Headers (If 403/401 occurs)
        if external_req.status_code in [401, 403]:
            print(f"Strategy 1 blocked ({external_req.status_code}). Retrying raw...")
            external_req = session.get(target_url, stream=True, verify=False, timeout=(10, 60))

        # Final Check
        if external_req.status_code >= 400:
            print(f"FINAL ERROR: {external_req.status_code} on {target_url}")
            raise HTTPException(status_code=400, detail=f"Upstream Server Blocked Request: {external_req.status_code}")

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

    except requests.exceptions.SSLError:
        print("SSL Error")
        raise HTTPException(status_code=500, detail="Source SSL Certificate Error")
    except requests.exceptions.ConnectionError:
        print("Connection Error")
        raise HTTPException(status_code=500, detail="Could not connect to video source")
    except requests.exceptions.Timeout:
        print("Timeout Error")
        raise HTTPException(status_code=504, detail="Source took too long to respond")
    except Exception as e:
        print(f"CRITICAL UNKNOWN: {str(e)}")
        raise HTTPException(status_code=500, detail=f"Stream Error: {str(e)}")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
