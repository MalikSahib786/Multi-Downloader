import os
import requests
from flask import Flask, render_template, request, jsonify, send_from_directory
from yt_dlp import YoutubeDL
from instaloader import Instaloader, Post

app = Flask(__name__)
app.config['DOWNLOAD_FOLDER'] = './downloads'
os.makedirs(app.config['DOWNLOAD_FOLDER'], exist_ok=True)

L = Instaloader()

def download_youtube(url):
    ydl_opts = {
        'format': 'best',
        'outtmpl': os.path.join(app.config['DOWNLOAD_FOLDER'], '%(title)s.%(ext)s'),
        'quiet': True
    }
    with YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        return ydl.prepare_filename(info)

def download_instagram(url):
    shortcode = url.split("/")[-2]
    post = Post.from_shortcode(L.context, shortcode)
    video_url = post.video_url
    filename = f"instagram_{shortcode}.mp4"
    save_path = os.path.join(app.config['DOWNLOAD_FOLDER'], filename)
    with open(save_path, 'wb') as f:
        f.write(requests.get(video_url).content)
    return filename

def download_facebook(url):
    ydl_opts = {
        'format': 'best',
        'outtmpl': os.path.join(app.config['DOWNLOAD_FOLDER'], '%(title)s.%(ext)s'),
        'quiet': True
    }
    with YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        return ydl.prepare_filename(info)

def download_tiktok(url):
    ydl_opts = {
        'format': 'best',
        'outtmpl': os.path.join(app.config['DOWNLOAD_FOLDER'], '%(title)s.%(ext)s'),
        'quiet': True
    }
    with YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        return ydl.prepare_filename(info)

@app.route('/')
def home():
    return render_template('index.html')

@app.route('/download', methods=['POST'])
def download():
    url = request.json['url']
    try:
        if 'youtube.com' in url or 'youtu.be' in url:
            filename = download_youtube(url)
        elif 'instagram.com' in url:
            filename = download_instagram(url)
        elif 'facebook.com' in url:
            filename = download_facebook(url)
        elif 'tiktok.com' in url:
            filename = download_tiktok(url)
        else:
            return jsonify({'error': 'Unsupported URL'}), 400

        return jsonify({'filename': os.path.basename(filename)})
    except Exception as e:
        return jsonify({'error': str(e)}), 500

@app.route('/downloads/<filename>')
def download_file(filename):
    return send_from_directory(app.config['DOWNLOAD_FOLDER'], filename, as_attachment=True)

if __name__ == '__main__':
    app.run(debug=True)