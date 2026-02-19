import os
import pandas as pd
from flask import Flask, request, send_file, render_template_string
from flask_apscheduler import APScheduler
from google.cloud import firestore
import yt_dlp
from datetime import datetime

app = Flask(__name__)
# Initialize Firestore (Ensure you have your service account JSON set up)
db = firestore.Client.from_service_account_json('path/to/your-key.json')

# --- SCHEDULER SETUP ---
scheduler = APScheduler()
scheduler.init_app(app)
scheduler.start()

@scheduler.task('interval', id='track_views_job', minutes=5)
def track_all_videos():
    # 1. Get all URLs from tracked_videos collection
    docs = db.collection('tracked_videos').stream()
    
    for doc in docs:
        url = doc.to_dict().get('url')
        try:
            with yt_dlp.YoutubeDL({'quiet': True}) as ydl:
                info = ydl.extract_info(url, download=False)
                views = info.get('view_count')
                
                # 2. Save new log to Firestore
                db.collection('view_logs').add({
                    'url': url,
                    'views': views,
                    'timestamp': datetime.now()
                })
                print(f"Tracked {views} views for {url}")
        except Exception as e:
            print(f"Error tracking {url}: {e}")

# --- ROUTES ---
@app.route('/add', methods=['POST'])
def add_url():
    url = request.form.get('url')
    db.collection('tracked_videos').add({'url': url, 'added_at': datetime.now()})
    return "URL added! Tracking started every 5 minutes."

@app.route('/export')
def export_excel():
    logs = db.collection('view_logs').order_by('timestamp').stream()
    data = [doc.to_dict() for doc in logs]
    
    df = pd.DataFrame(data)
    file_name = "youtube_stats.xlsx"
    df.to_excel(file_name, index=False)
    
    return send_file(file_name, as_attachment=True)

if __name__ == "__main__":
    app.run()