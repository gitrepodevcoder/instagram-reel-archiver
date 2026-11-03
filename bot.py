import os
import re
import json
import time
import base64
import threading
from http.server import HTTPServer, BaseHTTPRequestHandler
import requests
import yt_dlp
from google import genai
from google.genai import types

# Force IPv4 connection to prevent Windows/ISP IPv6 hanging issues with Telegram API
import urllib3.util.connection as urllib3_cn
def allowed_gai_family():
    import socket
    return socket.AF_INET
urllib3_cn.allowed_gai_family = allowed_gai_family

# Lightweight HTTP Health Server for Render / Cloud (Empty response)
class HealthServerHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        self.send_response(200)
        self.send_header('Content-type', 'text/plain; charset=utf-8')
        self.end_headers()
        self.wfile.write(b"")
    def log_message(self, format, *args):
        return  # Silence health check request logs

def start_health_server():
    port = int(os.environ.get("PORT", 8080))
    server = HTTPServer(("0.0.0.0", port), HealthServerHandler)
    server.serve_forever()

# Configuration from Environment Variables
TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "9260462505:AAFzJGE9m2McU3RLadehA2zs_FAU3Wx3zrs")
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "AQ.Ab8RN6IbKRFVlHiK4rcnT1Ajm6sUZcph_Df9E-uCjgXSaQFJtA")
WEBHOOK_URL = os.getenv("WEBHOOK_URL", "https://script.google.com/macros/s/AKfycbwGqjMFkzBZKu7wy00nJYGZIsP9oRpOjlMHpmPPc_VcsZDEQu4wI4nF44GPdxvBALY3/exec")

TELEGRAM_API_BASE = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}"

# Initialize Gemini Client
client = genai.Client(api_key=GEMINI_API_KEY)

os.makedirs("downloads", exist_ok=True)

def send_telegram_message(chat_id, text, reply_to_message_id=None):
    url = f"{TELEGRAM_API_BASE}/sendMessage"
    payload = {
        "chat_id": chat_id,
        "text": text,
        "parse_mode": "Markdown",
        "disable_web_page_preview": True
    }
    if reply_to_message_id:
        payload["reply_to_message_id"] = reply_to_message_id
    for attempt in range(2):
        try:
            requests.post(url, json=payload, timeout=25)
            break
        except Exception as e:
            print(f"Error sending message (attempt {attempt+1}): {e}")
            time.sleep(1)

def parse_urls(text):
    urls = re.findall(r'https?://[^\s]+', text)
    reel_url = None
    provided_link = ""

    for u in urls:
        if "instagram.com" in u and ("/reel/" in u or "/p/" in u or "/share/" in u):
            reel_url = u
        else:
            provided_link = u

    return reel_url, provided_link

def download_reel(url):
    ydl_opts = {
        'outtmpl': 'downloads/%(id)s.%(ext)s',
        'format': 'mp4/best',
        'quiet': True,
        'no_warnings': True,
    }
    with yt_dlp.YoutubeDL(ydl_opts) as ydl:
        info = ydl.extract_info(url, download=True)
        filename = ydl.prepare_filename(info)
        uploader = info.get("uploader") or info.get("channel") or "Unknown"
        reel_id = info.get("id") or str(int(time.time()))
        caption = info.get("description") or ""
        return filename, uploader, reel_id, caption

def analyze_with_gemini(video_path):
    print(f"Uploading {video_path} to Gemini API...")
    video_file = client.files.upload(file=video_path)
    
    # Wait for processing if needed
    while video_file.state.name == "PROCESSING":
        time.sleep(2)
        video_file = client.files.get(name=video_file.name)
        
    prompt = """Watch this Instagram reel video and listen to the audio carefully.
Analyze the content and respond with a strictly valid JSON object matching this schema:
{
  "summary": "Concise 2-3 sentence explanation in clear Hinglish/English of what this reel explains or demonstrates.",
  "detected_tool": "Name of the software, tool, library, or GitHub project shown or spoken.",
  "detected_link": "Official GitHub repo URL or website URL for this tool if shown, spoken, or known; otherwise empty string."
}
Return only the raw JSON without markdown code fences or backticks."""

    try:
        response = client.models.generate_content(
            model='gemini-3.5-flash',
            contents=[video_file, prompt]
        )
    except Exception as e:
        print(f"gemini-3.5-flash fallback to gemini-3.5-flash-lite: {e}")
        response = client.models.generate_content(
            model='gemini-3.5-flash-lite',
            contents=[video_file, prompt]
        )

    # Clean up uploaded file from Gemini storage
    try:
        client.files.delete(name=video_file.name)
    except Exception:
        pass

    text = response.text.strip()
    if text.startswith("```json"):
        text = text[7:]
    if text.startswith("```"):
        text = text[3:]
    if text.endswith("```"):
        text = text[:-3]
    text = text.strip()

    try:
        data = json.loads(text)
    except Exception:
        data = {
            "summary": response.text.strip(),
            "detected_tool": "Detected from video",
            "detected_link": ""
        }
    return data

def save_to_google_sheet_and_drive(reel_url, provided_link, creator, caption, ai_summary, video_path=None, reel_id=None):
    if not WEBHOOK_URL:
        print("WEBHOOK_URL not set, skipping Google Sheet append.")
        return None

    try:
        payload = {
            "reel_link": reel_url,
            "provided_link": provided_link,
            "creator": f"@{creator}" if not creator.startswith("@") else creator,
            "caption": caption,
            "ai_summary": ai_summary
        }

        if video_path and os.path.exists(video_path):
            with open(video_path, "rb") as f:
                payload["video_base64"] = base64.b64encode(f.read()).decode("utf-8")
            payload["video_name"] = f"{creator}_{reel_id}.mp4"

        resp = requests.post(WEBHOOK_URL, json=payload, timeout=60)
        return resp.json()
    except Exception as e:
        print(f"Error saving to Google Sheet/Drive: {e}")
        return None

def update_last_row_link(provided_link):
    if not WEBHOOK_URL:
        return None
    try:
        payload = {
            "action": "update_last_link",
            "provided_link": provided_link
        }
        resp = requests.post(WEBHOOK_URL, json=payload, timeout=20)
        return resp.json()
    except Exception as e:
        print(f"Error updating last link: {e}")
        return None

def process_message(message):
    chat_id = message["chat"]["id"]
    text = message.get("text", "")
    message_id = message["message_id"]

    reel_url, provided_link = parse_urls(text)

    # Follow-up: User sent only the tool/github link after the reel!
    if not reel_url and provided_link:
        res = update_last_row_link(provided_link)
        if res and res.get("status") == "success":
            row_num = res.get("updated_row", "last")
            send_telegram_message(chat_id, f"🔗 *Link Attached!*\nUpdated `Provided Link` on row #{row_num} with:\n`{provided_link}`", message_id)
        else:
            send_telegram_message(chat_id, f"ℹ️ Received link:\n`{provided_link}`\n_Send an Instagram reel first to attach this link to._", message_id)
        return

    if not reel_url:
        send_telegram_message(chat_id, "ℹ️ Please send an Instagram Reel link!\n\n_Example:_\n`https://www.instagram.com/reel/Cxxxx/`\n`https://github.com/project/name`", message_id)
        return

    send_telegram_message(chat_id, "⏳ *Processing Reel...*\nDownloading video & analyzing speech with Gemini AI...", message_id)

    video_path = None
    try:
        video_path, creator, reel_id, caption = download_reel(reel_url)
        ai_data = analyze_with_gemini(video_path)

        summary = ai_data.get("summary", "Summary generated")

        # Save to Google Sheet & Drive via Webhook
        sheet_res = save_to_google_sheet_and_drive(
            reel_url,
            provided_link,
            creator,
            caption,
            summary,
            video_path,
            reel_id
        )

        reply = f"✅ *Reel Successfully Archived!*\n\n"
        reply += f"👤 *Creator:* `@{creator}`\n"
        if provided_link:
            reply += f"🔗 *Provided Link:* {provided_link}\n"
        reply += f"\n📝 *AI Summary:*\n{summary}\n"

        if sheet_res and sheet_res.get("status") == "success":
            reply += f"\n📊 *Saved to Google Sheet!*"
        else:
            reply += f"\n📊 *Google Sheet:* Ready for Webhook connection."

        send_telegram_message(chat_id, reply, message_id)

    except Exception as e:
        print(f"Error processing reel: {e}")
        send_telegram_message(chat_id, f"❌ *Error processing reel:*\n`{str(e)}`", message_id)
    finally:
        if video_path and os.path.exists(video_path):
            try:
                os.remove(video_path)
            except Exception:
                pass

def main():
    print("Instagram Reel Archiver Bot is running...")
    
    # Start Cloud Health Server in background thread
    health_thread = threading.Thread(target=start_health_server, daemon=True)
    health_thread.start()
    print("Health server running on port " + os.getenv("PORT", "8080"))

    offset = None

    while True:
        try:
            url = f"{TELEGRAM_API_BASE}/getUpdates"
            params = {"timeout": 30}
            if offset:
                params["offset"] = offset

            resp = requests.get(url, params=params, timeout=40)
            if resp.status_code == 200:
                data = resp.json()
                for update in data.get("result", []):
                    offset = update["update_id"] + 1
                    if "message" in update and "text" in update["message"]:
                        process_message(update["message"])
        except Exception as e:
            print(f"Polling error: {e}")
            time.sleep(3)

if __name__ == "__main__":
    main()
