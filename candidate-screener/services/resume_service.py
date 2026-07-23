import io
import re
import requests
from pypdf import PdfReader

def extract_pdf_id_from_url(url: str) -> str:
    """Extract Google Drive file ID if applicable."""
    match = re.search(r'/d/([a-zA-Z0-9_-]+)', url)
    if match:
        return f"https://drive.google.com/uc?export=download&id={match.group(1)}"
    return url

def download_and_extract_resume(resume_url: str) -> str:
    """Downloads PDF from URL and parses raw text content."""
    if not resume_url or str(resume_url).strip().lower() in ['none', 'nan', '']:
        return "No resume link provided."
    
    download_url = extract_pdf_id_from_url(str(resume_url))
    
    try:
        response = requests.get(download_url, timeout=10)
        if response.status_code == 200:
            pdf_file = io.BytesIO(response.content)
            reader = PdfReader(pdf_file)
            text = "\n".join([page.extract_text() for page in reader.pages if page.extract_text()])
            return text if text.strip() else "Resume text could not be extracted (scanned/image PDF)."
        else:
            return f"Failed to download resume (HTTP {response.status_code})."
    except Exception as e:
        return f"Error reading resume: {str(e)}"