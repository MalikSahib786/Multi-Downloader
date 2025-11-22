import os
import random
import uvicorn  # <--- THIS WAS MISSING
import yt_dlp
from fastapi import FastAPI, HTTPException, Header, Depends
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

# --- CONFIGURATION ---
app = FastAPI(
    title="Ultimate Video Downloader API",
    description="API to extract direct video links from YouTube, TikTok, etc.",
    version="1.0.0"
)

# --- CORS MIDDLEWARE (Required for Frontend/Website) ---
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allows all websites to access this API
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# 1. SECURITY: Define your Secret API Key
SECRET_API_KEY = os.getenv("MY_API_KEY", "password123")

# 2. PROXIES: Load proxies from Environment Variable
PROXY_STRING = os.getenv("PROXY_LIST", "") 
PROXY_LIST = [p.strip() for p in PROXY_STRING.split(",")] if PROXY_STRING else []

# --- MODELS ---
class VideoRequest(BaseModel):
    url: str

# --- HELPER FUNCTIONS ---
async def verify_api_key(x_api_key: str = Header(None)):
    # If no key set in ENV, allow everyone. If key set, check it.
    if SECRET_API_KEY and x_api_key != SECRET_API_KEY:
        raise HTTPException(status_code=403, detail="Invalid API Key")

def get_random_proxy():
    if not PROXY_LIST:
        return None
    return random.choice(PROXY_LIST)

# --- API ENDPOINTS ---

@app.get("/")
def health_check():
    return {"status": "online", "service": "Multi-Downloader API"}

@app.post("/extract")
def extract_video_info(request: VideoRequest, authorized: bool = Depends(verify_api_key)):
    """
    Main endpoint to get video details.
    """
    url = request.url
    proxy = get_random_proxy()
    
    print(f"Processing: {url} | Using Proxy: {proxy}")

    ydl_opts = {
        'format': 'best', 
        'quiet': True,
        'no_warnings': True,
        'noplaylist': True,
        'extract_flat': False, 
        
        # NETWORK SETTINGS
        'proxy': proxy,
        'socket_timeout': 15,
        'retries': 3,
        'nocheckcertificate': True,
        'force_ipv4': True, # Fixes the DNS error
        
        # ANTI-BOT SETTINGS
        'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/115.0.0.0 Safari/537.36',
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            
            # Logic to find the best direct video link
            direct_url = info.get('url')
            
            # Fallback logic
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
        error_msg = str(e)
        print(f"Error: {error_msg}")
        if "Sign in" in error_msg:
            raise HTTPException(status_code=429, detail="Proxy Blocked by YouTube. Try again.")
        raise HTTPException(status_code=500, detail=error_msg)

if __name__ == "__main__":
    # Gets PORT from Railway, defaults to 8080
    port = int(os.environ.get("PORT", 8080))
    uvicorn.run(app, host="0.0.0.0", port=port)
