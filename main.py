import uvicorn
import requests
from urllib.parse import quote, unquote
from fastapi import FastAPI, HTTPException, Header, Depends, Query
from fastapi.responses import StreamingResponse
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

app = FastAPI(title="Cobalt Wrapper API", version="1.0")

app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_credentials=True, allow_methods=["*"], allow_headers=["*"],
)

MASTER_KEY = "123Lock.on"

# List of Public Cobalt API Instances (If one fails, we try the next)
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
            print(f"Trying instance: {api_base}")
            
            headers = {
                "Accept": "application/json",
                "Content-Type": "application/json",
                "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            }

            payload = {
                "url": url,
                "vCodec": "h264", # Ensures standard MP4
                "vQuality": "1080",
                "aFormat": "mp3",
                "filenamePattern": "basic"
            }

            response = requests.post(f"{api_base}/api/json", json=payload, headers=headers, timeout=10)
            
            if response.status_code == 200:
                data = response.json()
                
                # Cobalt returns diverse structures, we normalize them
                download_url = data.get("url")
                
                # If it's a "picker" (multiple qualities), grab the first one
                if not download_url and "picker" in data:
                    download_url = data["picker"][0]["url"]

                if download_url:
                    return {
                        "status": "success",
                        "title": data.get("filename", "video"),
                        "thumbnail": "https://cdn-icons-png.flaticon.com/512/2991/2991195.png", # Cobalt doesn't always send thumbs
                        "options": [{
                            "label": "Download High Quality",
                            "type": "video",
                            "url": download_url
                        }]
                    }
        except Exception as e:
            print(f"Instance {api_base} failed: {e}")
            continue

    raise HTTPException(status_code=400, detail="All servers are busy. Please try again later.")

@app.get("/stream")
def stream_content(target: str = Query(...), title: str = Query("file"), key: str = Query(...)):
    if key != MASTER_KEY:
        raise HTTPException(status_code=403, detail="Invalid Key")

    target_url = unquote(target)
    
    # Clean Filename
    safe_title = "".join([c for c in title if c.isalnum() or c in " _-"])[:50]
    if not safe_title: safe_title = "video"
    filename = f"{safe_title}.mp4"

    try:
        # Stream the file from Cobalt to User
        external_req = requests.get(target_url, stream=True, verify=False, timeout=60)
        
        return StreamingResponse(
            external_req.iter_content(chunk_size=64*1024),
            media_type="application/octet-stream",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'}
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Stream Error: {str(e)}")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
