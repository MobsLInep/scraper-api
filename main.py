from fastapi import FastAPI, HTTPException
from fastapi.responses import JSONResponse
from pydantic import BaseModel
import cloudscraper
from bs4 import BeautifulSoup
from urllib.parse import urljoin
import re
import os
import sqlite3
import firebase_admin
from firebase_admin import credentials, messaging
from datetime import datetime, timedelta

app = FastAPI()
BASE_URL = "https://codeforces.com"

FIREBASE_CRED_PATH = "/etc/secrets/serviceAccountKey.json"
if not firebase_admin._apps:
    cred = credentials.Certificate(FIREBASE_CRED_PATH)
    firebase_admin.initialize_app(cred)

DB_PATH = "users.db"

def init_db():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
    CREATE TABLE IF NOT EXISTS users (
        user_id TEXT PRIMARY KEY,
        fcm_token TEXT NOT NULL,
        notify_30min INTEGER DEFAULT 1,
        notify_10min INTEGER DEFAULT 1,
        notify_live INTEGER DEFAULT 1,
        notify_custom INTEGER DEFAULT 0,
        custom_minutes INTEGER DEFAULT 0
    )
    """)
    conn.commit()
    conn.close()

init_db()

def save_user(user_id, fcm_token, settings):
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("""
    INSERT OR REPLACE INTO users (user_id, fcm_token, notify_30min, notify_10min, notify_live, notify_custom, custom_minutes)
    VALUES (?, ?, ?, ?, ?, ?, ?)
    """, (
        user_id,
        fcm_token,
        int(settings.get("notify30min", True)),
        int(settings.get("notify10min", True)),
        int(settings.get("notifyLive", True)),
        int(settings.get("notifyCustom", False)),
        int(settings.get("customMinutes", 0))
    ))
    conn.commit()
    conn.close()

def get_all_users():
    conn = sqlite3.connect(DB_PATH)
    c = conn.cursor()
    c.execute("SELECT user_id, fcm_token, notify_30min, notify_10min, notify_live, notify_custom, custom_minutes FROM users")
    users = c.fetchall()
    conn.close()
    return users

def get_upcoming_contests():
    url = "https://codeforces.com/api/contest.list?gym=false"
    scraper = cloudscraper.create_scraper()
    resp = scraper.get(url)
    data = resp.json()
    contests = []
    if data["status"] == "OK":
        now = int(datetime.utcnow().timestamp())
        for contest in data["result"]:
            if contest["phase"] == "BEFORE":
                contests.append({
                    "id": contest["id"],
                    "name": contest["name"],
                    "startTimeSeconds": contest["startTimeSeconds"],
                    "relativeTimeSeconds": contest["startTimeSeconds"] - now
                })
    return contests

def send_fcm(fcm_token, title, body, data):
    try:
        message = messaging.Message(
            notification=messaging.Notification(
                title=title,
                body=body
            ),
            data={str(k): str(v) for k, v in data.items()},
            token=fcm_token
        )
        response = messaging.send(message)
        return True, response
    except Exception as e:
        print(f"Error sending FCM: {e}")
        return False, str(e)

class RegisterTokenRequest(BaseModel):
    userId: str
    fcmToken: str
    notificationSettings: dict

class SendTestNotificationRequest(BaseModel):
    fcmToken: str
    title: str
    body: str
    data: dict

@app.get("/health")
@app.head("/health")
def health_check():
    return {"status": "healthy", "service": "codeforces-scraper"}

@app.get("/")
@app.head("/")
def read_root():
    return {"message": "Codeforces Scraper API", "endpoints": ["/health", "/api/posts"]}

def process_post(post):
    title_div = post.find('div', class_='title')
    title = title_div.get_text(strip=True) if title_div else ""
    content_div = post.find('div', class_='content')
    if content_div:
        for a in content_div.find_all('a', href=True):
            user_class = a.get('class', [])
            username = a.get_text(strip=True)
            tag = None
            for c in user_class:
                if c in USER_CLASS_TO_TAG:
                    tag = USER_CLASS_TO_TAG[c]
                    break
            if tag:
                a.replace_with(f"<{tag}>{username}</{tag}>")
            else:
                a.replace_with(username)
        for a in content_div.find_all('a'):
            a.replace_with(a.get_text(strip=True))
        for img in content_div.find_all('img'):
            if img.has_attr('src'):
                img['src'] = urljoin(BASE_URL, img['src'])
        description = str(content_div)
    else:
        description = ""
    side_pic = None
    img = post.find('img')
    if img and img.has_attr('src'):
        side_pic = urljoin(BASE_URL, img['src'])
    return {
        "title": title,
        "description": description,
        "side_pic": side_pic
    }

USER_CLASS_TO_TAG = {
    'user-legendary': 'grandmaster',
    'user-red': 'grandmaster',
    'user-orange': 'master',
    'user-violet': 'candidate_master',
    'user-blue': 'expert',
    'user-cyan': 'specialist',
    'user-green': 'pupil',
    'user-gray': 'newbie',
    'user-black': 'unrated',
    'user-admin': 'admin',
}

@app.get("/api/posts")
def get_posts():
    url = BASE_URL + "/"
    scraper = cloudscraper.create_scraper()
    response = scraper.get(url)
    soup = BeautifulSoup(response.text, 'html.parser')
    page_content = soup.find('div', id='pageContent')
    posts = []
    if page_content:
        for post in page_content.find_all('div', class_='topic'):
            posts.append(process_post(post))
    return JSONResponse(posts)

@app.post("/api/register-token")
async def register_token(payload: RegisterTokenRequest):
    save_user(payload.userId, payload.fcmToken, payload.notificationSettings)
    print(f"Registered token for user {payload.userId}: {payload.fcmToken} with settings {payload.notificationSettings}")
    return {"status": "success", "message": "Token registered and settings saved"}

@app.post("/api/send-test-notification")
async def send_test_notification(payload: SendTestNotificationRequest):
    ok, resp = send_fcm(payload.fcmToken, payload.title, payload.body, payload.data)
    if ok:
        return {"status": "success", "message": "Notification sent", "firebase_response": resp}
    else:
        return {"status": "error", "details": resp}, 500

@app.post("/api/cron")
async def cron_trigger():
    print("Cron job triggered!")
    users = get_all_users()
    contests = get_upcoming_contests()
    now = int(datetime.utcnow().timestamp())
    for contest in contests:
        for user in users:
            user_id, fcm_token, notify_30min, notify_10min, notify_live, notify_custom, custom_minutes = user
            seconds_to_start = contest["startTimeSeconds"] - now
            if notify_30min and 1740 <= seconds_to_start <= 1860:
                send_fcm(
                    fcm_token,
                    f"Contest Reminder: {contest['name']}",
                    "Contest starts in 30 minutes!",
                    {"type": "contest_reminder", "contestId": contest["id"], "contestName": contest["name"], "reminder": "30min"}
                )
            if notify_10min and 540 <= seconds_to_start <= 660:
                send_fcm(
                    fcm_token,
                    f"Contest Reminder: {contest['name']}",
                    "Contest starts in 10 minutes!",
                    {"type": "contest_reminder", "contestId": contest["id"], "contestName": contest["name"], "reminder": "10min"}
                )
            if notify_live and -60 <= seconds_to_start <= 60:
                send_fcm(
                    fcm_token,
                    f"Contest Live: {contest['name']}",
                    "Contest is now live!",
                    {"type": "contest_live", "contestId": contest["id"], "contestName": contest["name"]}
                )
            if notify_custom and custom_minutes > 0:
                custom_sec = custom_minutes * 60
                if (custom_sec - 60) <= seconds_to_start <= (custom_sec + 60):
                    send_fcm(
                        fcm_token,
                        f"Contest Reminder: {contest['name']}",
                        f"Contest starts in {custom_minutes} minutes!",
                        {"type": "contest_reminder", "contestId": contest["id"], "contestName": contest["name"], "reminder": f"{custom_minutes}min"}
                    )
    return {"status": "ok"}
