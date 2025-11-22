import os
import uvicorn
from fastapi import FastAPI, HTTPException
import yt_dlp
import random

app = FastAPI()

# Proxies list (Jo aapne webshare ki batayi thi)
PROXY_LIST = [
    # Yahan apni proxies daalain: "http://user:pass@ip:port"
]

def get_random_proxy():
    if not PROXY_LIST:
        return None
    return random.choice(PROXY_LIST)

@app.get("/")
def home():
    return {"message": "API is running live on Railway!"}

@app.post("/process")
def process_video(data: dict):
    url = data.get("url")
    proxy_url = get_random_proxy()
    
    ydl_opts = {
        'format': 'best',
        'quiet': True,
        'noplaylist': True,
        'proxy': proxy_url, # Webshare proxy
        'nocheckcertificate': True,
    }

    try:
        with yt_dlp.YoutubeDL(ydl_opts) as ydl:
            info = ydl.extract_info(url, download=False)
            return {
                "status": "success",
                "title": info.get('title'),
                "video_url": info.get('url'),
                "thumbnail": info.get('thumbnail')
            }
    except Exception as e:
        return {"status": "error", "message": str(e)}

if __name__ == "__main__":
    # YEH LINE SABSE ZAROORI HAI RAILWAY KE LIYE
    port = int(os.environ.get("PORT", 8000)) 
    uvicorn.run(app, host="0.0.0.0", port=port)
