from fastapi import FastAPI, HTTPException, Header, Depends
from fastapi.middleware.cors import CORSMiddleware # <--- IMPORT THIS
from pydantic import BaseModel
import yt_dlp
import os
import random

app = FastAPI()

# --- ADD THIS CORS BLOCK ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allows all websites to access your API (Change this for security later)
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
# --- CONFIGURATION ---
app = FastAPI(
    title="Ultimate Video Downloader API",
    description="API to extract direct video links from YouTube, TikTok, etc.",
    version="1.0.0"
)

# 1. SECURITY: Define your Secret API Key here (or use Env Variable)
# Users must send this key in the header 'x-api-key'
SECRET_API_KEY = os.getenv("MY_API_KEY", "secret-12345")

# 2. PROXIES: Add your Webshare proxies here
# Format: "http://username:password@ip:port"
# In production, it is better to load this from an Environment Variable
PROXY_STRING = os.getenv("PROXY_LIST", "") 
PROXY_LIST = [p.strip() for p in PROXY_STRING.split(",")] if PROXY_STRING else []

# --- MODELS ---
class VideoRequest(BaseModel):
    url: str

# --- HELPER FUNCTIONS ---
async def verify_api_key(x_api_key: str = Header(...)):
    if x_api_key != SECRET_API_KEY:
        raise HTTPException(status_code=403, detail="Invalid API Key")

def get_random_proxy():
    if not PROXY_LIST:
        return None
    return random.choice(PROXY_LIST)

# --- API ENDPOINTS ---

@app.get("/")
def health_check():
    return {"status": "online", "service": "Multi-Downloader API"}

@app.post("/extract", dependencies=[Depends(verify_api_key)])
def extract_video_info(request: VideoRequest):
    """
    Main endpoint to get video details.
    Requires 'x-api-key' header.
    """
    url = request.url
    proxy = get_random_proxy()
    
    print(f"Processing: {url} | Using Proxy: {proxy}")

    ydl_opts = {
        'format': 'best', # Get best quality
        'quiet': True,
        'no_warnings': True,
        'noplaylist': True,
        'extract_flat': False, # We need full details
        
        # NETWORK SETTINGS
        'proxy': proxy,
        'socket_timeout': 15,
        'retries': 3,
        'nocheckcertificate': True,
        
        # ANTI-BOT SETTINGS
        'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36',
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            
            # Logic to find the best direct video link (MP4 with Audio)
            direct_url = info.get('url')
            
            # If 'url' is missing (common in some formats), try to find formats
            if not direct_url and 'formats' in info:
                for f in info['formats']:
                    if f.get('ext') == 'mp4' and f.get('acodec') != 'none':
                        direct_url = f['url']
                        break
            
            return {
                "status": "success",
                "platform": info.get('extractor'),
                "title": info.get('title'),
                "duration": info.get('duration'),
                "thumbnail": info.get('thumbnail'),
                "download_url": direct_url,
                "views": info.get('view_count')
            }

    except Exception as e:
        # Error handling
        error_msg = str(e)
        if "Sign in" in error_msg:
            raise HTTPException(status_code=429, detail="Proxy Blocked by YouTube. Try again.")
        raise HTTPException(status_code=500, detail=error_msg)

if __name__ == "__main__":
    # Gets PORT from Railway, defaults to 8000
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="0.0.0.0", port=port)
