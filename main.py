from fastapi import FastAPI, HTTPException
import yt_dlp
import random

app = FastAPI()

# ---------------------------------------------------------
# 1. APNI WEBSHARE PROXY LIST YAHAN DALEIN
# Format: "http://username:password@ip:port"
# ---------------------------------------------------------
PROXY_LIST = [
    "http://user:pass@1.2.3.4:8000",
    "http://user:pass@5.6.7.8:8000",
    "http://user:pass@9.10.11.12:8000",
    # Jitni zyada proxies hongi, utna kam block hoga
]

def get_random_proxy():
    if not PROXY_LIST:
        return None
    return random.choice(PROXY_LIST)

@app.get("/")
def home():
    return {"message": "API is running!"}

@app.post("/process")
def process_video(data: dict):
    url = data.get("url")
    if not url:
        raise HTTPException(status_code=400, detail="URL required")

    # Random Proxy select karein
    proxy_url = get_random_proxy()
    
    print(f"Using Proxy: {proxy_url}") # Debugging ke liye

    ydl_opts = {
        'format': 'best',
        'quiet': True,
        'noplaylist': True,
        'extract_flat': True, # Sirf info chahiye, download nahi karna server par
        
        # ----------------------------------------------
        # Yahan Proxy Inject ho rahi hai
        # ----------------------------------------------
        'proxy': proxy_url, 
        
        # Extra settings to avoid detection
        'nocheckcertificate': True,
        'user_agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/90.0.4430.212 Safari/537.36',
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            
            return {
                "status": "success",
                "title": info.get('title'),
                "video_url": info.get('url'),  # Direct Link
                "thumbnail": info.get('thumbnail'),
                "duration": info.get('duration')
            }
            
    except Exception as e:
        # Agar error aaye to shayad Proxy block ho gayi hai
        return {"status": "error", "message": str(e), "proxy_used": proxy_used}

# Local run karne ke liye: uvicorn main:app --reload
