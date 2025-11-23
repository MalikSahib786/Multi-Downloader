import os
import uvicorn
from curl_cffi import requests # <--- THE SECRET WEAPON
from urllib.parse import quote, unquote
from fastapi import FastAPI, HTTPException, Header, Depends, Query
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(title="Browser-Based API", version="Shortcut.1.0")

app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"],
)

MASTER_KEY = "123Lock.on"

# We use multiple Cobalt instances. If one is down, we auto-switch.
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

@app.post("/extract", dependencies=[Depends(verify_api_key)])
def extract_media(request: MediaRequest):
    url = request.url
    print(f"🚀 Processing via Browser Engine: {url}")

    # We loop through instances until one works
    for api_base in COBALT_INSTANCES:
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

            # IMPERSONATE CHROME 120
            # This fixes the DNS error and the Blocking error simultaneously
            response = requests.post(
                f"{api_base}/api/json", 
                json=payload, 
                headers=headers, 
                impersonate="chrome120", # <--- MAGIC LINE
                timeout=10
            )
            
            if response.status_code == 200:
                data = response.json()
                
                download_url = data.get("url")
                
                # Handle Pickers (Multiple formats)
                if not download_url and "picker" in data:
                    download_url = data["picker"][0]["url"]

                if download_url:
                    return {
                        "status": "success",
                        "title": data.get("filename", "Media_File"),
                        "thumbnail": "https://cdn-icons-png.flaticon.com/512/567/567013.png",
                        "options": [{
                            "label": "Download Best Quality",
                            "type": "video",
                            "url": download_url,
                            # Cobalt URLs often have the size in the header, but we assume unknown for speed
                            "filesize": 0 
                        }]
                    }
        except Exception as e:
            print(f"Instance {api_base} failed: {e}")
            continue

    # If all fail
    raise HTTPException(status_code=500, detail="All servers are busy. Please try again later.")

@app.get("/stream")
def stream_content(target: str = Query(...), title: str = Query("file"), key: str = Query(...)):
    if key != MASTER_KEY:
        raise HTTPException(status_code=403, detail="Invalid Key")

    target_url = unquote(target)
    
    # Sanitize Title
    safe_title = "".join([c for c in title if c.isalnum() or c in " _-"])[:50]
    if not safe_title: safe_title = "video"
    filename = f"{safe_title}.mp4"

    try:
        # Stream using Chrome Impersonation
        # This allows us to download from servers that block Python
        r = requests.get(target_url, stream=True, impersonate="chrome120", timeout=60)
        
        def iterfile():
            for chunk in r.iter_content(chunk_size=64*1024):
                if chunk: yield chunk

        return StreamingResponse(
            iterfile(),
            media_type="application/octet-stream",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'}
        )
    except Exception as e:
        print(f"Stream Error: {e}")
        raise HTTPException(status_code=500, detail="Stream Failed")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
