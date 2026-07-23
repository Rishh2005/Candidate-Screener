import os
import time
import json
from groq import Groq

# Initialize Groq client
client = Groq(api_key=os.environ.get("GROQ_API_KEY"))

# Use 8B model for much higher daily token limits (500k vs 100k)
MODEL_NAME = "llama-3.1-8b-instant" 

def evaluate_candidate_with_ai(candidate_dict, resume_text, github_info, job_description):
    """
    Evaluates a candidate profile against the JD using Groq LLM with rate limit handling,
    exponential backoff, and strict text truncation to conserve tokens.
    """
    # 1. TRUNCATE INPUTS TO PREVENT TOKEN EXHAUSTION
    truncated_resume = str(resume_text)[:1200] if resume_text else "No resume provided"
    truncated_github = str(github_info)[:800] if github_info else "No GitHub link provided"
    truncated_jd = str(job_description)[:1000] if job_description else "General role"

    prompt = f"""
    You are an expert technical recruiter evaluating an applicant for a job.
    
    Candidate Info:
    Name: {candidate_dict.get('name', 'N/A')}
    
    Job Description:
    {truncated_jd}
    
    Resume Snippet:
    {truncated_resume}
    
    GitHub Summary Snippet:
    {truncated_github}
    
    Evaluate the candidate alignment. Provide output ONLY as valid JSON in this exact structure:
    {{
        "jd_relevance_score": <number 0-100>,
        "github_score": <number 0-100>,
        "overall_score": <number 0-100>,
        "reasoning": "<brief 1-2 sentence summary of candidate fit>"
    }}
    """

    # 2. RETRY LOOP WITH EXPONENTIAL BACKOFF FOR 429 ERRORS
    max_retries = 5
    backoff_seconds = 3

    for attempt in range(max_retries):
        try:
            response = client.chat.completions.create(
                model=MODEL_NAME,
                messages=[
                    {"role": "system", "content": "You are a JSON-only applicant scoring assistant."},
                    {"role": "user", "content": prompt}
                ],
                temperature=0.2,
                response_format={"type": "json_object"}
            )
            
            raw_content = response.choices[0].message.content
            parsed = json.loads(raw_content)
            
            return {
                "jd_relevance_score": parsed.get("jd_relevance_score", 70),
                "github_score": parsed.get("github_score", 70),
                "overall_score": parsed.get("overall_score", 70),
                "reasoning": parsed.get("reasoning", "Candidate profile evaluated successfully.")
            }

        except Exception as e:
            err_str = str(e).lower()
            # If rate limited (429), pause and retry automatically
            if "429" in err_str or "rate_limit" in err_str:
                if attempt < max_retries - 1:
                    time.sleep(backoff_seconds)
                    backoff_seconds *= 2  # Exponential backoff (3s, 6s, 12s...)
                    continue
            
            # Fallback output if retries fail or other errors occur
            return {
                "jd_relevance_score": 65,
                "github_score": 65,
                "overall_score": 65,
                "reasoning": f"Automated scoring fallback due to API throttling ({type(e).__name__})."
            }