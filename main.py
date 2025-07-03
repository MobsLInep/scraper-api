from fastapi import FastAPI
from fastapi.responses import JSONResponse
from fastapi import Request
from pydantic import BaseModel
import cloudscraper
from bs4 import BeautifulSoup
from urllib.parse import urljoin
import re
import os

import firebase_admin
from firebase_admin import credentials, messaging

app = FastAPI()
BASE_URL = "https://codeforces.com"

FIREBASE_CRED_PATH = "/etc/secrets/serviceAccountKey.json"
if not firebase_admin._apps:
    cred = credentials.Certificate(FIREBASE_CRED_PATH)
    firebase_admin.initialize_app(cred)

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

class RegisterTokenRequest(BaseModel):
    userId: str
    fcmToken: str
    notificationSettings: dict

class SendTestNotificationRequest(BaseModel):
    fcmToken: str
    title: str
    body: str
    data: dict

@app.post("/api/register-token")
async def register_token(payload: RegisterTokenRequest):
    print(f"Registering token for user {payload.userId}: {payload.fcmToken} with settings {payload.notificationSettings}")
    return {"status": "success", "message": "Token registered (not persisted in demo)"}

@app.post("/api/send-test-notification")
async def send_test_notification(payload: SendTestNotificationRequest):
    try:
        message = messaging.Message(
            notification=messaging.Notification(
                title=payload.title,
                body=payload.body
            ),
            data={str(k): str(v) for k, v in payload.data.items()},
            token=payload.fcmToken
        )
        response = messaging.send(message)
        return {"status": "success", "message": "Notification sent", "firebase_response": response}
    except Exception as e:
        return {"status": "error", "details": str(e)}, 500

@app.post("/api/cron")
async def cron_trigger():
    # Your logic to check for upcoming contests and send notifications
    # For demo, just print/log
    print("Cron job triggered!")
    # TODO: Add your contest notification logic here
    return {"status": "ok"}
