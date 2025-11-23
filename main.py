import uvicorn
import requests
from urllib.parse import quote, unquote
from fastapi import FastAPI, HTTPException, Header, Depends, Query
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(title="Cluster Media API", version="Fast.2.0")

app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"],
)

MASTER_KEY = "123Lock.on"

# --- PUBLIC INSTANCE LIST (The Engine) ---
# These are public, high-speed instances that handle the blocking for us.
PIPED_INSTANCES = [
    "https://pipedapi.kavin.rocks",
    "https://api.piped.privacy.com.de",
    "https://pipedapi.drgns.space",
    "https://pa.il.ax",
    "https://api.piped.yt"
]

COBALT_INSTANCES = [
    "https://api.cobalt.tools",
    "https://co.wuk.sh",
    "https://cobalt.api.kwiatekmiki.pl",
    "https://api.server.cobalt.tools"
]

class MediaRequest(BaseModel):
    url: str

async def verify_api_key(x_api_key: str = Header(None)):
    if x_api_key != MASTER_KEY:
        raise HTTPException(status_code=403, detail="Access Denied")

def format_size(bytes_size):
    if not bytes_size: return "Unknown Size"
    return f"{round(bytes_size / 1024 / 1024, 1)} MB"

# --- YOUTUBE HANDLER (Via Piped) ---
def process_youtube(video_id):
    print(f"⚡ contacting Piped Cluster for ID: {video_id}")
    
    for api in PIPED_INSTANCES:
        try:
            # 1. Get Metadata
            r = requests.get(f"{api}/streams/{video_id}", timeout=5)
            if r.status_code != 200: continue
            
            data = r.json()
            options = []
            
            # 2. Extract Video Streams
            for s in data.get("videoStreams", []):
                if s.get("videoOnly", False) is False: # We want Video + Audio
                    res = s.get("quality", "Unknown")
                    size = s.get("contentLength", 0)
                    options.append({
                        "label": f"{res} ({format_size(size)})",
                        "type": "video",
                        "url": s["url"],
                        "filesize": size
                    })

            # 3. Extract Audio Streams
            for a in data.get("audioStreams", []):
                size = a.get("contentLength", 0)
                options.append({
                    "label": f"Audio Only ({format_size(size)})",
                    "type": "audio",
                    "url": a["url"],
                    "filesize": size
                })

            if options:
                return {
                    "status": "success",
                    "title": data["title"],
                    "thumbnail": data["thumbnailUrl"],
                    "source": "YouTube (Piped)",
                    "options": options
                }
        except:
            continue
    return None

# --- SOCIAL HANDLER (Via Cobalt) ---
def process_social(url):
    print(f"⚡ contacting Cobalt Cluster for: {url}")
    
    for api in COBALT_INSTANCES:
        try:
            headers = {
                "Accept": "application/json",
                "Content-Type": "application/json"
            }
            payload = {
                "url": url,
                "vCodec": "h264",
                "vQuality": "1080",
                "aFormat": "mp3",
                "filenamePattern": "basic"
            }
            
            r = requests.post(f"{api}/api/json", json=payload, headers=headers, timeout=8)
            if r.status_code != 200: continue
            
            data = r.json()
            link = data.get("url")
            
            # Fallback for Pickers
            if not link and "picker" in data:
                link = data["picker"][0]["url"]
            
            if link:
                # Cobalt doesn't give size, so we do a quick HEAD request
                size = 0
                try:
                    head = requests.head(link, timeout=2)
                    size = int(head.headers.get("Content-Length", 0))
                except: pass

                return {
                    "status": "success",
                    "title": data.get("filename", "Social Video"),
                    "thumbnail": "https://cdn-icons-png.flaticon.com/512/1946/1946552.png",
                    "source": "Social (Cobalt)",
                    "options": [{
                        "label": f"HD Video ({format_size(size)})",
                        "type": "video",
                        "url": link,
                        "filesize": size
                    }]
                }
        except:
            continue
    return None

@app.post("/extract", dependencies=[Depends(verify_api_key)])
def extract_media(request: MediaRequest):
    url = request.url
    
    # 1. Router Logic
    if "youtube.com" in url or "youtu.be" in url:
        # Extract ID logic
        vid_id = url.split("v=")[-1].split("&")[0] if "v=" in url else url.split("/")[-1].split("?")[0]
        result = process_youtube(vid_id)
    else:
        # TikTok, Insta, FB, Twitter
        result = process_social(url)

    if result:
        return result
        
    raise HTTPException(status_code=400, detail="Server Busy. Please try again.")

@app.get("/stream")
def stream_content(target: str = Query(...), title: str = Query("file"), size: int = Query(None), key: str = Query(...)):
    if key != MASTER_KEY:
        raise HTTPException(status_code=403, detail="Invalid Key")

    target_url = unquote(target)
    
    # Headers
    headers = {
        "User-Agent": "Mozilla/5.0",
        "Connection": "keep-alive"
    }
    
    # File Info
    safe_title = "".join([c for c in title if c.isalnum() or c in " _-"])[:50]
    filename = f"{safe_title}.mp4"
    if "audio" in title.lower(): filename = f"{safe_title}.mp3"

    # Response Headers
    resp_headers = {"Content-Disposition": f'attachment; filename="{filename}"'}
    if size: resp_headers["Content-Length"] = str(size)

    try:
        # Stream directly from the Source (Piped/Cobalt)
        # verify=False handles any SSL issues on Railway
        external_req = requests.get(target_url, headers=headers, stream=True, verify=False, timeout=30)
        
        return StreamingResponse(
            external_req.iter_content(chunk_size=64*1024),
            media_type=external_req.headers.get("content-type", "application/octet-stream"),
            headers=resp_headers
        )
    except Exception as e:
        print(f"Stream Error: {e}")
        raise HTTPException(status_code=500, detail="Connection Lost")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
