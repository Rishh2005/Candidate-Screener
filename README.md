# AI Candidate Screener & Resume Parser

I built this project to solve a real problem recruiters face during hiring drives: sifting through dozens of resumes manually is tedious and time-consuming. 

This tool automates the initial candidate screening process. It extracts text from PDF and Word resumes, parses contact information, calculates how closely a candidate's background matches a Job Description using vector embeddings, and generates structured hiring feedback with custom interview questions.

---

## Quick Links
* **Live Demo:** [https://candidate-screener-demo.streamlit.app](https://candidate-screener-demo.streamlit.app)
---

## How It Works (Under the Hood)

Instead of relying on basic keyword searches that miss good candidates, the pipeline processes resumes in 5 steps:

1. **Document Parsing (`pdfplumber`, `python-docx`):** Opens uploaded PDFs or Word files and extracts raw text while preserving multi-column layouts and tables.
2. **Entity Extraction (`spaCy`, RegEx):** Uses regular expressions to grab email addresses and phone numbers, and `spaCy` Named Entity Recognition (NER) to pull out the candidate's name.
3. **Embedding Generation (`sentence-transformers` / OpenAI):** Converts both the resume text and the job description into dense numerical vectors to understand semantic meaning rather than exact word matches.
4. **Semantic Scoring (`FAISS`, Cosine Similarity):** Calculates the mathematical similarity between the candidate's experience vector and the job description vector to output a match score (0–100%).
5. **Structured AI Screening (`LangChain`, `Pydantic`):** Passes the extracted text and match score to an LLM with a strict JSON output schema. The model returns:
   * Estimated years of experience
   * Matched vs. missing skill breakdown
   * Screening decision (`SHORTLIST`, `REJECT`, or `MANUAL_REVIEW`)
   * Brief reasoning summary
   * 3 technical interview questions targeted at the candidate's skill gaps

---

## Tech Stack

* **Language:** Python 3.9+
* **Parsing & Extraction:** `pdfplumber`, `python-docx`, `spaCy` (`en_core_web_sm`), `re`
* **Vector Matcher:** `sentence-transformers`, `FAISS`, `NumPy`
* **LLM Framework:** `LangChain`, `Pydantic v2`
* **UI & API:** `Streamlit`, `FastAPI`

---

## Setup & Local Installation

Want to run this on your local machine? Follow these steps:

### 1. Clone the repo
```bash
git clone [https://github.com/rishabhjain/candidate-screener.git](https://github.com/rishabhjain/candidate-screener.git)
cd candidate-screener
```

### 2. Create a virtual environment
```bash
python -m venv env
source env/bin/activate  # On Windows: .\env\Scripts\activate
```

### 3. Install requirements & spaCy model
```bash
pip install -r requirements.txt
python -m spacy download en_core_web_sm
```

### 4. Configure environment variables
Create a `.env` file in the project root and add your API key:
```env
OPENAI_API_KEY="your-openai-api-key"
# OR
GEMINI_API_KEY="your-gemini-api-key"
```

### 5. Run the web interface
```bash
streamlit run app.py
```

---

## Sample Output Payload

When a resume goes through the pipeline, the backend outputs a clean structured JSON object like this:

```json
{
  "candidate_name": "Rishabh Jain",
  "match_percentage": 88.5,
  "years_of_experience": 2.5,
  "matched_skills": ["Python", "FastAPI", "LangChain", "Vector Databases"],
  "missing_skills": ["Kubernetes", "AWS Lambda"],
  "screening_decision": "SHORTLIST",
  "key_reasoning": "Strong candidate with solid foundations in Python, LLMs, and API building. Lacks cloud infrastructure experience.",
  "generated_interview_questions": [
    "How do you handle API rate limits and retries when calling LLM endpoints?",
    "Can you explain how vector similarity search works in FAISS?",
    "What steps do you take to enforce strict JSON schemas on model responses?"
  ]
}
```

---

## Edge Cases & Guardrails

* **Parsing Fallback:** If an uploaded file is corrupted or extracts fewer than 50 characters, the app immediately flags it as `STATUS_PARSING_FAILED` to prevent downstream pipeline errors.
* **Rate Limit Handling:** Built-in exponential backoff retries API calls automatically if rate limits (HTTP 429) are encountered.
* **PII Privacy:** Contact information is stripped before raw resume text gets passed into third-party LLM prompt calls.
