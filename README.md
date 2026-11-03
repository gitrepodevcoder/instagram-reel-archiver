# Instagram Reel Archiver & AI Summarizer Bot

A 24/7 automated pipeline that listens to Instagram Reel links (+ optional project links) via Telegram, downloads video using `yt-dlp` and `ffmpeg`, transcribes and summarizes the video using Google Gemini AI (`gemini-2.5-flash`), uploads the MP4 archive directly to Google Drive, and logs the full metadata into a styled Google Sheet.

[![Deploy to Render](https://render.com/images/deploy-to-render-button.svg)](https://render.com/deploy?repo=https://github.com/gitrepodevcoder/instagram-reel-archiver)

## Features
- **yt-dlp + ffmpeg Containerized**: Cloud-ready Docker container with zero local dependency required.
- **Multimodal AI Analysis**: Listens to speech, detects mentioned tools/repos, and writes a clean Hinglish summary using Gemini 2.5 Flash.
- **Google Drive Storage**: Encodes and uploads reel MP4s to `Instagram_Tech_Reels` folder.
- **Google Sheets Sync**: Appends rows with S.No, Reel Link, Provided Link, Creator, Original Caption, AI Summary, Watch Link, and Date.
- **Follow-up Link Attachment**: Automatically updates the last row if you send the GitHub link after the reel!

## 1-Click 24/7 Cloud Deployment (Free)

### Method 1: Render.com (Recommended)
1. Click the **Deploy to Render** button above or open [Render.com](https://dashboard.render.com/).
2. Log in with GitHub and select repository `gitrepodevcoder/instagram-reel-archiver`.
3. Choose **Web Service** -> Environment **Docker** -> Plan **Free**.
4. The environment variables are automatically loaded from `render.yaml`! Click **Deploy Web Service**.
5. Done! The bot will now run 24/7 even when your computer is completely off.

### Method 2: Koyeb / Hugging Face Spaces (Docker)
- Choose **Docker**, connect repository `gitrepodevcoder/instagram-reel-archiver`.
- Set Environment variables:
  - `TELEGRAM_BOT_TOKEN`: Your Telegram Bot Token
  - `GEMINI_API_KEY`: Your Gemini API Key
  - `WEBHOOK_URL`: Your Google Apps Script Exec URL
  - `PORT`: `8080` (or `7860` for Hugging Face)
