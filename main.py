from fastapi import FastAPI
from fastapi.responses import JSONResponse
import cloudscraper
from bs4 import BeautifulSoup
from urllib.parse import urljoin
import re

app = FastAPI()
BASE_URL = "https://codeforces.com"

# Helper to process user profile links into tags
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

# Health check endpoint for UptimeRobot (supports both GET and HEAD)
@app.get("/health")
@app.head("/health")
def health_check():
    return {"status": "healthy", "service": "codeforces-scraper"}

# Root endpoint (supports both GET and HEAD)
@app.get("/")
@app.head("/")
def read_root():
    return {"message": "Codeforces Scraper API", "endpoints": ["/health", "/api/posts"]}

def process_post(post):
    # Title
    title_div = post.find('div', class_='title')
    title = title_div.get_text(strip=True) if title_div else ""
    
    # Content
    content_div = post.find('div', class_='content')
    if content_div:
        # Replace user profile links with tags
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
        
        # Remove all other hyperlinks but keep text
        for a in content_div.find_all('a'):
            a.replace_with(a.get_text(strip=True))
        
        # Make image src absolute
        for img in content_div.find_all('img'):
            if img.has_attr('src'):
                img['src'] = urljoin(BASE_URL, img['src'])
        
        description = str(content_div)
    else:
        description = ""
    
    # Side pic (first image in post, if any)
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
