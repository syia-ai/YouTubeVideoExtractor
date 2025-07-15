# !pip install requests openai pandas google-api-python-client python-dotenv pickle-mixin google-auth-oauthlib google-auth pydantic langchain langchain-openai tqdm

import os
import requests
import openai
import pandas as pd
from datetime import datetime, timedelta, timezone
from googleapiclient.discovery import build
from dotenv import load_dotenv
import pickle
from google_auth_oauthlib.flow import InstalledAppFlow
from google.auth.transport.requests import Request
from pydantic import BaseModel
from typing import List, Literal
from langchain_openai import ChatOpenAI
from langchain.prompts import ChatPromptTemplate
from langchain.output_parsers import PydanticOutputParser
from tqdm import tqdm
import base64
import io
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from google.auth.transport.requests import Request
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
import re

load_dotenv()

# Load client credentials from environment
YOUTUBE_CLIENT_ID = os.getenv("oauth_client_id")
YOUTUBE_CLIENT_SECRET = os.getenv("oauth_client_secret")
SEARCH_API_KEY = os.getenv("searchapi_key")
OPENAI_API_KEY = os.getenv("openai_key")

SCOPES = ["https://www.googleapis.com/auth/youtube.readonly"]

def youtube_authenticate_with_keys(client_id, client_secret):
    creds = None

    if os.path.exists("youtube_token.pickle"):
        with open("youtube_token.pickle", "rb") as token:
            creds = pickle.load(token)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_config(
                {
                    "installed": {
                        "client_id": client_id,
                        "client_secret": client_secret,
                        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                        "token_uri": "https://oauth2.googleapis.com/token",
                        "redirect_uris": ["http://localhost"]
                    }
                },
                SCOPES
            )
            creds = flow.run_local_server(port=0)

        with open("youtube_token.pickle", "wb") as token:
            pickle.dump(creds, token)

    return build("youtube", "v3", credentials=creds)

# from IPython.core.display import display, HTML
# display(HTML(html))

SCOPES = ['https://www.googleapis.com/auth/gmail.send']

def gmail_authenticate_with_keys(client_id, client_secret):
    creds = None

    # Reuse token if available
    if os.path.exists('gmail_token.pickle'):
        with open('gmail_token.pickle', 'rb') as token_file:
            creds = pickle.load(token_file)

    # Refresh if expired or prompt new login
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_config(
                {
                    "installed": {
                        "client_id": client_id,
                        "client_secret": client_secret,
                        "auth_uri": "https://accounts.google.com/o/oauth2/auth",
                        "token_uri": "https://oauth2.googleapis.com/token",
                        "redirect_uris": ["http://localhost"]
                    }
                },
                SCOPES
            )
            creds = flow.run_local_server(port=0)
            # Save the new token
            with open('gmail_token.pickle', 'wb') as token_file:
                pickle.dump(creds, token_file)

    return build('gmail', 'v1', credentials=creds)


# Example usage
gmail_service = gmail_authenticate_with_keys(YOUTUBE_CLIENT_ID, YOUTUBE_CLIENT_SECRET)

def send_email(service, sender, to, subject, body_text, cc=None):
    message = MIMEMultipart()
    message["to"] = to
    message["from"] = sender
    message["subject"] = subject
    if cc:
        message["Cc"] = cc

    # Attach HTML body
    message.attach(MIMEText(body_text, "html"))

    # Encode and send the email
    raw_message = base64.urlsafe_b64encode(message.as_bytes()).decode()

    try:
        sent_message = service.users().messages().send(
            userId="me",
            body={"raw": raw_message}
        ).execute()
        print(f"Email sent! ID: {sent_message['id']}")
        return sent_message
    except Exception as e:
        print(f"Failed to send email: {e}")
        return None

def extract_video_id_from_link(link):
    match = re.search(r"v=([\w-]+)", link)
    if match:
        return match.group(1)
    else:
        raise ValueError("Invalid YouTube video link format.")

def get_video_details(youtube, video_id):
    request = youtube.videos().list(
        part="snippet",
        id=video_id
    )
    response = request.execute()
    items = response.get("items", [])
    if not items:
        raise ValueError(f"No video found for ID: {video_id}")
    item = items[0]
    return {
        "video_id": video_id,
        "title": item["snippet"]["title"],
        "channel": item["snippet"]["channelTitle"],
        "published_date": item["snippet"]["publishedAt"]
    }

def get_transcript(video_id): #This transcript extraction process uses SerpApi Key
    url = "https://www.searchapi.io/api/v1/search"
    params = {
        "engine": "youtube_transcripts",
        "api_key": SEARCH_API_KEY,
        "video_id": video_id
    }
    response = requests.get(url, params=params)
    data = response.json()
    transcript = " ".join([entry["text"] for entry in data.get("transcripts", [])])
    return transcript

# def get_transcript(video_id):

#     url = f"https://ytb2mp4.com/api/fetch-transcript?url=https://www.youtube.com/watch?v={video_id}"
#     response = requests.get(url)
#     if response.status_code == 200:
#         try:
#             data = response.json()
#             if isinstance(data, dict) and "transcript" in data:
#                 if isinstance(data["transcript"], list):
#                     transcript = " ".join([item["text"] for item in data["transcript"]])
#                 elif isinstance(data["transcript"], str):
#                     transcript = data["transcript"]
#                 else:
#                     transcript = "Unexpected transcript format."
#             else:
#                 transcript = "Transcript key not found in API response."
#         except requests.exceptions.JSONDecodeError:
#             transcript = "Error decoding JSON. Response may not be in JSON format."
#     else:
#         transcript = f"Error fetching transcript: {response.status_code}"
    
#     return transcript

def summarize_transcript(data):

    title = data['title']
    channel = data['channel']
    transcript = data['transcript']
    published_date = data['published_date']
    videoId = data['video_id']

    class GetSummary(BaseModel):
        summary: str

    # Assume OutputFormat is your pydantic model
    parser = PydanticOutputParser(pydantic_object=GetSummary)
    escaped_format_instructions = parser.get_format_instructions().replace("{", "{{").replace("}", "}}")

    system_message = f"""
    You are a helpful assistant that summarizes content into a well-structured format using HTML. 
    Summarize the contents of the video based on the title and transcript, grouping the points into precise and meaningful themes, and presenting the result in HTML format. 
    Ensure the output is impactful, clear, and properly structured. 
    Focus on thematic grouping and avoid excessive granularity. 
    
    Present the summary in HTML format as follows:\n\n
    1. Provide a high-level overview of the main topic in a `<h2>` tag.\n
    2. Group related points into categories or themes, each with a `<h3>` heading.\n
    3. Use `<ul>` and `<li>` tags for bullet points within each theme.\n
    4. Ensure the result is structured, concise, and impactful, while valid for rendering in an email client. 
    
    Always return the summary strictly in the below mentioned JSON format: 
    Response format:
    {escaped_format_instructions}
    """

    chat = ChatOpenAI(
        model="gpt-4o-mini",
        temperature=0,
        openai_api_key=OPENAI_API_KEY
    )

    prompt = ChatPromptTemplate.from_messages([
        ("system", system_message),
        ("user", "{input}")
    ])

    chain = prompt | chat | parser

    parsed_output = chain.invoke({
        "input": f"Title: {title}\n\nChannel:{channel}\n\nTranscript:{transcript}\n\nPublished Date:{published_date}\n\nVideo ID:{videoId}\n\n"
    })
    # Convert to dictionary
    parsed_response = parsed_output.model_dump()

    return parsed_response

def format_html(summary_data):
    title = summary_data['title']
    channel = summary_data['channel']
    summary = summary_data['summary']
    video_id = summary_data['video_id']

    published_date = summary_data['published_date']
    published_date_obj = datetime.fromisoformat(published_date.replace("Z", "+00:00"))
    published_date_str = published_date_obj.strftime("%d %b %Y")

    html = f"""
<h1><strong>{title}</strong></h1>
<h3>{channel}, {published_date_str}</h3>
{summary}<br>
<b>LINK:</b> <a href="https://www.youtube.com/watch?v={video_id}">Watch the video on YouTube</a>
<br><br><br><br>
    """
    return html


def main_video_extractor(VIDEO_LINK):

    # Authenticate and fetch video
    youtube_service = youtube_authenticate_with_keys(YOUTUBE_CLIENT_ID, YOUTUBE_CLIENT_SECRET)

    # Extract video ID from the provided link
    video_id = extract_video_id_from_link(VIDEO_LINK)

    # Get details for the single video
    video_detail = get_video_details(youtube_service, video_id)

    # Process the single video
    html = "<ul>\n"
    try:
        transcript = get_transcript(video_detail['video_id'])
        video_detail['transcript'] = transcript
        summarydict = summarize_transcript(video_detail)
        video_detail['summary'] = summarydict['summary']
        html += format_html(video_detail)
    except Exception as e:
        print(f"Failed to summarize {video_detail['video_id']}: {e}")

    html += "</ul>"

    if html != '<ul>\n</ul>':
        send_email(
            service=gmail_service,
            sender="agent@siya.com",
            to="syiadomainteam@synergyship.com, prashant.s@synergyship.com",
            subject="Latest Tech Updates from YouTube",
            body_text=html,
            cc='sulagna.b@synergyship.com'
        )
    return


VIDEO_LINK = "https://www.youtube.com/watch?v=2WM3CQhc1bY"  
main_video_extractor(VIDEO_LINK)
