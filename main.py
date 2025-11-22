import os
import uvicorn
import yt_dlp
from fastapi import FastAPI, HTTPException, Header, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# --- CONFIGURATION ---
app = FastAPI(
    title="Professional Video Downloader",
    version="2.0.0"
)

# --- CORS (Required for your Frontend) ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- REAL CREDENTIAL SYSTEM ---
# We hardcode it here so there are NO mistakes with Environment Variables
# You must send "x-api-key: 123Lock.on" in your request headers.
MASTER_KEY = "123Lock.on"

# --- INPUT MODEL ---
class VideoRequest(BaseModel):
    url: str

# --- SECURITY FUNCTION ---
async def verify_api_key(x_api_key: str = Header(None)):
    """
    Enforces strict authentication.
    """
    if x_api_key != MASTER_KEY:
        # Logs the attempt for security monitoring
        print(f"🚫 Unauthorized Access Attempt with key: '{x_api_key}'")
        raise HTTPException(status_code=403, detail="Access Denied: Invalid Credential")

# --- API ENDPOINT ---
@app.get("/")
def home():
    return {"status": "Active", "system": "Direct Railway Connection"}

@app.post("/extract", dependencies=[Depends(verify_api_key)])
def extract_video_info(request: VideoRequest):
    url = request.url
    print(f"⚡ Processing: {url} (Direct Connection)")

    # Configuration for Railway Direct Connection
    ydl_opts = {
        'format': 'best',
        'quiet': True,
        'no_warnings': True,
        'noplaylist': True,
        
        # CRITICAL FOR RAILWAY:
        'force_ipv4': True,      # Forces usage of standard internet
        'nocheckcertificate': True,
        'socket_timeout': 30,    # Longer timeout for large videos
        
        # SPOOFING (Pretend to be a regular browser, not a bot)
        'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            # Extract Info
            info = ydl.extract_info(url, download=False)
            
            # Smart Link Extraction
            direct_url = info.get('url')
            
            # If standard URL fails, look for specific MP4 formats
            if not direct_url and 'formats' in info:
                for f in info['formats']:
                    if f.get('ext') == 'mp4' and f.get('acodec') != 'none':
                        direct_url = f['url']
                        break
            
            return {
                "status": "success",
                "title": info.get('title'),
                "thumbnail": info.get('thumbnail'),
                "download_url": direct_url,
                "duration": info.get('duration'),
                "source": "Direct-Railway"
            }

    except Exception as e:
        error_msg = str(e)
        print(f"❌ Error: {error_msg}")
        
        # Handle common blocks
        if "Sign in" in error_msg:
            raise HTTPException(status_code=429, detail="YouTube blocked this Railway Server. Try again later.")
        
        raise HTTPException(status_code=500, detail=error_msg)

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
