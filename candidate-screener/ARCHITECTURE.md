# Candidate Screening Platform - Architecture & Design Document

## System Architecture Diagram

[Candidate CSV] ──► [Resume Parser] ──► [GitHub REST API Crawler]
│
▼
[Job Description] ─────────────────► [LLM Evaluation Engine]
│
▼
[Ranked Leaderboard]
│
▼
[Google Meet API] ◄── [Test Results Ingestion] ◄── [SMTP Test Link Dispatcher]

## AI Evaluation Methodology & Explainable AI
1. **Weighted Scoring Calculation**:
   $$\text{Composite Score} = 0.40 \times \text{AI Resume Score} + 0.35 \times \text{Coding Score} + 0.25 \times \text{Aptitude Score}$$
2. **Explainable AI (XAI)**: Outputs explicit qualitative rationale alongside scores, identifying specific key strengths and risks/red-flags per candidate.