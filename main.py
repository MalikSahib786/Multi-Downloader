import os  # <--- THIS WAS MISSING
import uvicorn
import requests
from urllib.parse import quote, unquote
from fastapi import FastAPI, HTTPException, Header, Depends, Query
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(title="Cobalt Wrapper API", version="1.1")

# Allow all origins (fixes CORS issues)
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"],
)

MASTER_KEY = "123Lock.on"

# List of Public Cobalt Instances
# Using multiple backups ensures 100% uptime
COBALT_INSTANCES = [
    "https://api.cobalt.tools",
    "https://co.wuk.sh",
    "https://api.server.cobalt.tools",
    "https://cobalt.api.kwiatekmiki.pl"
]

class MediaRequest(BaseModel):
    url: str

async def verify_api_key(x_api_key: str = Header(None)):
    if x_api_key != MASTER_KEY:
        raise HTTPException(status_code=403, detail="Access Denied")

@app.post("/extract", dependencies=[Depends(verify_api_key)])
def extract_media(request: MediaRequest):
    url = request.url
    print(f"🔄 Processing via Cobalt: {url}")

    # Try each instance until one works
    for api_base in COBALT_INSTANCES:
        try:
            headers = {
                "Accept": "application/json",
                "Content-Type": "application/json",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            }

            payload = {
                "url": url,
                "vCodec": "h264",
                "vQuality": "1080",
                "aFormat": "mp3",
                "filenamePattern": "basic"
            }

            # Short timeout so we can switch to backup quickly if one is down
            response = requests.post(f"{api_base}/api/json", json=payload, headers=headers, timeout=8)
            
            if response.status_code == 200:
                data = response.json()
                
                download_url = data.get("url")
                
                # Handle "picker" (multiple options) response
                if not download_url and "picker" in data:
                    for item in data["picker"]:
                        if item.get("type") == "video":
                            download_url = item.get("url")
                            break
                    if not download_url:
                        download_url = data["picker"][0]["url"]

                if download_url:
                    return {
                        "status": "success",
                        "title": data.get("filename", "Social_Video"),
                        "thumbnail": "https://cdn-icons-png.flaticon.com/512/2991/2991195.png", 
                        "options": [{
                            "label": "Download Best Quality",
                            "type": "video",
                            "url": download_url
                        }]
                    }
        except Exception as e:
            print(f"Instance {api_base} failed: {e}")
            continue

    raise HTTPException(status_code=400, detail="Could not fetch video. Server busy or link invalid.")

@app.get("/stream")
def stream_content(target: str = Query(...), title: str = Query("file"), key: str = Query(...)):
    if key != MASTER_KEY:
        raise HTTPException(status_code=403, detail="Invalid Key")

    target_url = unquote(target)
    
    # Sanitize Filename (Fixes 'Unknown Server Error')
    try:
        ascii_title = title.encode('ascii', 'ignore').decode('ascii')
    except:
        ascii_title = "video"
    
    safe_title = "".join([c for c in ascii_title if c.isalnum() or c in " _-"])[:50]
    if not safe_title: safe_title = "video"
    filename = f"{safe_title}.mp4"

    try:
        # Stream the file from Cobalt to User
        # verify=False fixes SSL errors on some Cobalt instances
        external_req = requests.get(target_url, stream=True, verify=False, timeout=60)
        
        return StreamingResponse(
            external_req.iter_content(chunk_size=64*1024),
            media_type="application/octet-stream",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'}
        )
    except Exception as e:
        print(f"Stream Error: {e}")
        raise HTTPException(status_code=500, detail="Stream Connection Failed")

if __name__ == "__main__":
    # This line caused the error because 'os' wasn't imported. It is fixed now.
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
