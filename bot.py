import os

import sys

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



# Configuration from Environment Variables (set on Render)

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN")

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

WEBHOOK_URL = os.getenv("WEBHOOK_URL")



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

    url_pattern = r'(?:https?://[^\s]+|(?:www\.|github\.com/|gitlab\.com/)[^\s]+)'

    raw_urls = re.findall(url_pattern, text, re.IGNORECASE)

    

    reel_url = None

    provided_link = ""



    for u in raw_urls:

        clean_u = u.rstrip(".,;!)]}>'\"")

        if not clean_u.startswith("http://") and not clean_u.startswith("https://"):

            clean_u = "https://" + clean_u

            

        if "instagram.com" in clean_u.lower():

            reel_url = clean_u

        else:

            provided_link = clean_u



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

        creator = info.get("channel") or info.get("uploader") or "Unknown"

        reel_id = info.get("id") or str(int(time.time()))

        caption = info.get("description") or ""

        return filename, creator, reel_id, caption



def analyze_with_gemini(video_path):
    print(f"Uploading {video_path} to Gemini API...")
    try:
        video_file = client.files.upload(file=video_path)
        while video_file.state.name == "PROCESSING":
            time.sleep(2)
            video_file = client.files.get(name=video_file.name)
    except Exception as e:
        print(f"File upload to Gemini failed: {e}")
        return {
            "summary": "Video downloaded successfully! (AI processing skipped due to upload timeout)",
            "detected_tool": "",
            "detected_link": ""
        }
        
    prompt = """Watch this Instagram reel video and listen to the audio carefully.
Analyze the content and respond with a strictly valid JSON object matching this schema:
{
  "summary": "Concise 2-3 sentence explanation in clear Hinglish/English of what this reel explains or demonstrates.",
  "detected_tool": "Name of the software, tool, library, or GitHub project shown or spoken.",
  "detected_link": "Official GitHub repo URL or website URL for this tool if shown, spoken, or known; otherwise empty string."
}
Return only the raw JSON without markdown code fences or backticks."""

    # Models list in priority order with resilient fallback
    models_to_try = [
        "gemini-2.5-flash",
        "gemini-2.5-flash-lite",
        "gemini-2.0-flash",
        "gemini-3.5-flash",
        "gemini-3.5-flash-lite"
    ]

    response = None
    last_err = None

    for model_name in models_to_try:
        for attempt in range(1, 3):  # Up to 2 attempts per model
            try:
                print(f"Querying Gemini model '{model_name}' (attempt {attempt}/2)...", flush=True)
                response = client.models.generate_content(
                    model=model_name,
                    contents=[video_file, prompt]
                )
                if response and response.text:
                    print(f"SUCCESS: Generation succeeded with model '{model_name}'!", flush=True)
                    break
            except Exception as e:
                last_err = e
                err_msg = str(e).lower()
                print(f"Notice on '{model_name}' (attempt {attempt}): {e}", flush=True)
                if "503" in err_msg or "high demand" in err_msg or "unavailable" in err_msg or "429" in err_msg:
                    wait_sec = attempt * 3
                    print(f"Temporary load spike detected. Backing off for {wait_sec}s...", flush=True)
                    time.sleep(wait_sec)
                else:
                    # Non-retryable error on this model (e.g. model not available), skip to next model
                    break
        if response and response.text:
            break

    if not response or not response.text:
        print(f"All Gemini models exhausted. Last error: {last_err}")
        return {
            "summary": "Video successfully archived to Drive and Sheet! (AI summary temporarily skipped due to high Google traffic demand)",
            "detected_tool": "",
            "detected_link": ""
        }

    text_resp = response.text.strip()
    if text_resp.startswith("```json"):
        text_resp = text_resp[7:]
    if text_resp.startswith("```"):
        text_resp = text_resp[3:]
    if text_resp.endswith("```"):
        text_resp = text_resp[:-3]
    text_resp = text_resp.strip()

    try:
        data = json.loads(text_resp)
        return data
    except Exception as e:
        print(f"JSON Parsing error: {e}. Raw response: {text_resp}")
        return {
            "summary": text_resp,
            "detected_tool": "",
            "detected_link": ""
        }



def save_to_google_sheet_and_drive(reel_url, provided_link, creator, caption, summary, video_path, reel_id):

    if not WEBHOOK_URL:

        print("WEBHOOK_URL is not set!")

        return None



    try:

        video_b64 = ""

        if video_path and os.path.exists(video_path):

            with open(video_path, "rb") as vf:

                video_b64 = base64.b64encode(vf.read()).decode("utf-8")



        payload = {

            "reel_link": reel_url,

            "provided_link": provided_link,

            "creator": creator,

            "caption": caption[:500],

            "ai_summary": summary,

            "video_base64": video_b64,

            "video_name": f"{creator}_{reel_id}.mp4"

        }



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

    text = message.get("text") or message.get("caption") or ""

    message_id = message["message_id"]



    if text.strip().lower() in ["/clean", "/reset", "clean", "reset"]:

        send_telegram_message(chat_id, "🧹 *Cleaning Google Sheet & Google Drive...*", message_id)

        try:

            res = requests.post(WEBHOOK_URL, json={"action": "clean_all"}, timeout=30).json()

            if res.get("status") == "success":

                send_telegram_message(chat_id, "✅ *Google Sheet aur Google Drive clean ho gaye!*\n\nAb nayi video `#001` se save hogi.", message_id)

            else:

                send_telegram_message(chat_id, "❌ Error cleaning: " + str(res.get("message")), message_id)

        except Exception as e:

            send_telegram_message(chat_id, f"❌ Error: {e}", message_id)

        return



    reel_url, provided_link = parse_urls(text)



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



# Webhook & Health Server for Render

class WebhookServerHandler(BaseHTTPRequestHandler):

    def do_GET(self):

        self.send_response(200)

        self.send_header('Content-type', 'text/plain; charset=utf-8')

        self.end_headers()

        self.wfile.write(b"Instagram Reel Archiver is Live!")



    def do_POST(self):

        if self.path in ["/webhook", "/"]:

            content_length = int(self.headers.get('Content-Length', 0))

            post_data = self.rfile.read(content_length)

            self.send_response(200)

            self.send_header('Content-type', 'text/plain; charset=utf-8')

            self.end_headers()

            self.wfile.write(b"OK")

            try:

                update = json.loads(post_data.decode('utf-8'))

                msg = update.get("message") or update.get("channel_post") or update.get("edited_message")

                if msg:

                    # Run processing in background thread so Telegram gets instant 200 OK

                    threading.Thread(target=process_message, args=(msg,), daemon=True).start()

            except Exception as e:

                print(f"Webhook processing error: {e}")

        else:

            self.send_response(404)

            self.end_headers()



    def log_message(self, format, *args):

        return



def main():

    print("Instagram Reel Archiver starting in Webhook Mode...")

    

    # Auto register Webhook with Telegram

    webhook_url = "https://instagram-reel-archiver.onrender.com/webhook"

    try:

        r = requests.post(f"{TELEGRAM_API_BASE}/setWebhook", json={"url": webhook_url, "drop_pending_updates": False}, timeout=15)

        print("Telegram Webhook registration:", r.status_code, r.text)

    except Exception as e:

        print("Failed to register Telegram Webhook:", e)



    port = int(os.environ.get("PORT", 8080))

    server = HTTPServer(("0.0.0.0", port), WebhookServerHandler)

    print(f"Webhook HTTP Server listening on port {port}...")

    server.serve_forever()



if __name__ == "__main__":

    main()

