import os
import uuid
from google.oauth2 import service_account
from googleapiclient.discovery import build

SCOPES = ['https://www.googleapis.com/auth/calendar']

def schedule_google_meet(candidate_name: str, candidate_email: str, start_time_iso: str, end_time_iso: str) -> dict:
    creds_path = os.getenv("GOOGLE_CREDENTIALS_FILE", "service_account.json")
    calendar_id = os.getenv("RECRUITER_CALENDAR_ID", "primary")
    
    if not os.path.exists(creds_path):
        # Mock link generation if service account is not supplied
        mock_meet = f"https://meet.google.com/mock-{uuid.uuid4().hex[:3]}-{uuid.uuid4().hex[:4]}"
        return {"meet_link": mock_meet, "status": "Mock Created (Add service_account.json for real API)"}
        
    try:
        creds = service_account.Credentials.from_service_account_file(creds_path, scopes=SCOPES)
        service = build('calendar', 'v3', credentials=creds)
        
        event = {
            'summary': f'GTM Engineering Interview - {candidate_name}',
            'description': f'Interview with {candidate_name} for the GTM Engineering Intern role.',
            'start': {'dateTime': start_time_iso, 'timeZone': 'Asia/Kolkata'},
            'end': {'dateTime': end_time_iso, 'timeZone': 'Asia/Kolkata'},
            'attendees': [{'email': candidate_email}],
            'conferenceData': {
                'createRequest': {
                    'requestId': str(uuid.uuid4()),
                    'conferenceSolutionKey': {'type': 'hangoutsMeet'}
                }
            }
        }
        
        event = service.events().insert(
            calendarId=calendar_id, 
            body=event, 
            conferenceDataVersion=1
        ).execute()
        
        meet_link = event.get('hangoutLink', '')
        return {"meet_link": meet_link, "event_id": event.get('id'), "status": "Success"}
    except Exception as e:
        return {"error": str(e), "status": "Failed"}