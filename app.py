import os
import pandas as pd
import yt_dlp
from datetime import datetime
from flask import Flask, request, render_template, send_file, redirect, url_for
from flask_apscheduler import APScheduler
from google.cloud import firestore

# --- INITIALIZATION ---
app = Flask(__name__)

# Initialize Firestore
# Make sure 'serviceAccountKey.json' is in your main project folder
db = firestore.Client.from_service_account_json('serviceAccountKey.json')

# --- BACKGROUND TRACKER (SCHEDULER) ---
scheduler = APScheduler()
scheduler.init_app(app)
scheduler.start()

@scheduler.task('interval', id='track_views_task', minutes=5)
def track_youtube_views():
    """Background job that grabs views for all saved URLs every 5 minutes."""
    print(f"[{datetime.now()}] Starting background view check...")
    
    # Get all unique URLs we need to track
    videos_ref = db.collection('tracked_videos').stream()
    
    for doc in videos_ref:
        video_data = doc.to_dict()
        url = video_data.get('url')
        
        try:
            ydl_opts = {'quiet': True, 'no_warnings': True}
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                view_count = info.get('view_count')
                
                # Save the snapshot to the logs collection
                db.collection('view_logs').add({
                    'url': url,
                    'views': view_count,
                    'timestamp': datetime.now() # Firestore saves this as a Timestamp object
                })
                print(f"Logged {view_count} views for: {url}")
        except Exception as e:
            print(f"Failed to track {url}: {e}")

# --- WEB ROUTES ---

@app.route('/')
def index():
    """Home page: Shows input box or the data table if a URL is provided."""
    target_url = request.args.get('url')
    logs_data = []

    if target_url:
        # Fetch logs for this specific URL from Firestore
        # We order by timestamp descending to show newest first
        logs_ref = db.collection('view_logs') \
                     .where('url', '==', target_url) \
                     .order_by('timestamp', direction=firestore.Query.DESCENDING) \
                     .limit(100) \
                     .stream()
        
        for log in logs_ref:
            data = log.to_dict()
            logs_data.append({
                'Views': f"{data['views']:,}", # Format numbers with commas
                'Time': data['timestamp'].strftime("%Y-%m-%d %H:%M")
            })

    return render_template('index.html', current_url=target_url, logs=logs_data)

@app.route('/add', methods=['POST'])
def add_url():
    """Adds a new URL to the tracking list."""
    url = request.form.get('url').strip()
    if url:
        # Check if it's already in our tracking list
        existing = db.collection('tracked_videos').where('url', '==', url).get()
        if not existing:
            db.collection('tracked_videos').add({
                'url': url,
                'added_on': datetime.now()
            })
    # Redirect back to home with the URL in the query string
    return redirect(url_for('index', url=url))

@app.route('/export')
def export():
    """Generates an Excel file for the specific URL."""
    target_url = request.args.get('url')
    if not target_url:
        return "No URL specified for export", 400

    logs_ref = db.collection('view_logs') \
                 .where('url', '==', target_url) \
                 .order_by('timestamp', direction=firestore.Query.ASCENDING) \
                 .stream()
    
    export_data = []
    for log in logs_ref:
        d = log.to_dict()
        export_data.append({
            'URL': d['url'],
            'View Count': d['views'],
            'Timestamp': d['timestamp'].replace(tzinfo=None) # Excel doesn't like timezones
        })
    
    if not export_data:
        return "No data found to export", 404

    df = pd.DataFrame(export_data)
    file_path = "youtube_view_report.xlsx"
    df.to_excel(file_path, index=False)
    
    return send_file(file_path, as_attachment=True)

# --- RUN APP ---
if __name__ == "__main__":
    # Get port from environment (Render requirement)
    port = int(os.environ.get("PORT", 5000))
    app.run(host='0.0.0.0', port=port)
