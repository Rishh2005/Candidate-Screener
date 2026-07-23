import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

from services.ai_evaluator import evaluate_candidate_with_ai
from services.calendar_service import schedule_google_meet
from services.email_service import send_email
from services.github_service import analyze_github_profile
from services.resume_service import download_and_extract_resume

load_dotenv()

st.set_page_config(page_title="Candidate Screener & Scheduler", layout="wide")

st.title("Candidate Screening & Interview Platform")
st.caption("Evaluate applicants, check GitHub profiles, rank candidates, and send interview invites.")

# Session state initializations
if "candidates_df" not in st.session_state:
    st.session_state.candidates_df = None
if "evaluations" not in st.session_state:
    st.session_state.evaluations = pd.DataFrame()
if "final_ranked" not in st.session_state:
    st.session_state.final_ranked = None

# Sidebar controls
st.sidebar.header("Control Panel")
role_title = st.sidebar.text_input("Job Role Title", value="", placeholder="e.g. Full Stack AI Engineer")
jd_text = st.sidebar.text_area(
    "Job Description", 
    height=150, 
    value="",
    placeholder="Paste job description here..."
)
interview_desc = st.sidebar.text_area(
    "Interview Details",
    height=150,
    value="",
    placeholder="Enter interview format, expectations, etc."
)

tab1, tab2, tab3, tab4 = st.tabs([
    "1. Applicant Evaluation", 
    "2. Assessment Dispatch", 
    "3. Test Scoring & Ranking", 
    "4. Interview Scheduler"
])


def get_field(row, possible_keys, default_val="N/A"):
    """Helper function to pull a column value using common header aliases."""
    for key in possible_keys:
        if key in row and pd.notna(row[key]):
            val = str(row[key]).strip()
            if val:
                return val
    return default_val


def clean_dataframe(df):
    """Clean column names by removing whitespace and lowercasing."""
    if df is None or df.empty:
        return df
    cleaned = df.copy()
    cleaned.columns = cleaned.columns.str.strip().str.lower()
    return cleaned


def evaluate_single_candidate(index, row, role, job_desc):
    """Background task to fetch candidate context and run AI evaluation."""
    name = get_field(row, ["name", "candidate_name", "full_name"], f"Candidate {index + 1}")
    email = get_field(row, ["email", "email_address", "mail"], "")

    # Fetch resume text if link is present
    resume_url = get_field(row, ["resume", "resume_link", "pdf"], "")
    resume_text = download_and_extract_resume(resume_url) if resume_url else "No resume provided"

    # Fetch GitHub details if link is present
    github_url = get_field(row, ["github", "github_link", "profile"], "")
    github_info = analyze_github_profile(github_url) if github_url else "No GitHub link provided"

    context_jd = f"Role: {role}\nDescription: {job_desc}" if role else job_desc
    ai_result = evaluate_candidate_with_ai(row.to_dict(), resume_text, github_info, context_jd)

    output = row.to_dict()
    output.update({
        "name": name,
        "email": email,
        "github_summary": github_info
    })
    output.update(ai_result)
    return output


def dispatch_interview_email(candidate, role, description, start_time, end_time, meet_link):
    """Sends a single interview invitation email with the Google Meet link."""
    name = candidate.get("name", "Candidate")
    email = candidate.get("email", "").strip()

    if not email or "@" not in email:
        return False, name, "Invalid Email"

    # Default fallback if meet_link is blank
    final_link = meet_link.strip() if meet_link and meet_link.strip() else "https://meet.google.com/qcu-gewh-qth"

    email_body = f"""
    <p>Hi {name},</p>
    <p>Congrats! We would like to invite you for an interview for the <b>{role}</b> role.</p>
    <p><b>Interview Details:</b><br>{description}</p>
    <p><b>Date & Time:</b> {start_time}</p>
    <p><b>Google Meet Link:</b> <a href="{final_link}">{final_link}</a></p>
    <p>Best regards,<br>Hiring Team</p>
    """

    try:
        send_email(email, f"Interview Invitation - {role}", email_body)
        return True, name, email
    except Exception as err:
        return False, name, str(err)


# --- TAB 1: EVALUATION ---
with tab1:
    st.header("Step 1: Upload Candidates & Evaluate")
    uploaded_file = st.file_uploader("Upload Candidates (CSV / Excel)", type=["csv", "xlsx"])

    if uploaded_file:
        if uploaded_file.name.endswith(".csv"):
            data = pd.read_csv(uploaded_file)
        else:
            data = pd.read_excel(uploaded_file)

        st.session_state.candidates_df = data
        st.dataframe(data.head(5), use_container_width=True)

        if st.button("Start AI Evaluation"):
            if not jd_text.strip():
                st.warning("Please fill in the Job Description in the sidebar first.")
            else:
                progress_bar = st.progress(0)
                status = st.empty()
                status.text("Evaluating candidates...")

                total_rows = len(data)
                results = [None] * total_rows

                with ThreadPoolExecutor(max_workers=4) as executor:
                    futures_map = {}
                    for idx, row in data.iterrows():
                        future = executor.submit(evaluate_single_candidate, idx, row, role_title, jd_text)
                        futures_map[future] = idx
                        time.sleep(0.1)

                    completed = 0
                    for future in as_completed(futures_map):
                        idx = futures_map[future]
                        try:
                            results[idx] = future.result()
                        except Exception as e:
                            st.error(f"Error processing row {idx + 1}: {e}")
                        completed += 1
                        progress_bar.progress(completed / total_rows)

                status.empty()
                valid_results = [r for r in results if r is not None]
                st.session_state.evaluations = pd.DataFrame(valid_results)
                st.success(f"Successfully evaluated {len(valid_results)} candidates!")

    if isinstance(st.session_state.evaluations, pd.DataFrame) and not st.session_state.evaluations.empty:
        st.subheader("Leaderboard")
        eval_df = clean_dataframe(st.session_state.evaluations)
        score_column = "overall_score" if "overall_score" in eval_df.columns else "ai score"
        
        display_cols = [c for c in ["name", "email", score_column, "jd_relevance_score", "github_score", "reasoning"] if c in eval_df.columns]
        st.dataframe(eval_df[display_cols], use_container_width=True)


# --- TAB 2: DISPATCH ASSESSMENTS ---
with tab2:
    st.header("Step 2: Dispatch Online Assessment")
    if isinstance(st.session_state.evaluations, pd.DataFrame) and not st.session_state.evaluations.empty:
        eval_df = clean_dataframe(st.session_state.evaluations)

        if "email" not in eval_df.columns:
            mail_cols = [c for c in eval_df.columns if "email" in c or "mail" in c]
            eval_df["email"] = eval_df[mail_cols[0]] if mail_cols else "N/A"

        if "name" not in eval_df.columns:
            eval_df["name"] = [f"Candidate {i+1}" for i in range(len(eval_df))]

        eval_df["label"] = eval_df.apply(
            lambda r: f"{r['name']} ({r['email']})" if pd.notna(r['email']) and str(r['email']).strip() != "" else str(r['name']),
            axis=1
        )

        candidate_options = eval_df["label"].tolist()
        selected_candidates = st.multiselect("Select Candidates for Assessment", options=candidate_options, default=candidate_options)
        test_link = st.text_input("Assessment Link", "https://forms.gle/sample_assessment_link")
        current_role = role_title.strip() if role_title.strip() else "the position"

        if st.button(f"Dispatch Assessment Emails ({len(selected_candidates)})"):
            if not selected_candidates:
                st.warning("Please select at least one candidate.")
            else:
                progress_bar = st.progress(0)
                status = st.empty()
                sent_count = 0
                failed_candidates = []

                sub_df = eval_df[eval_df["label"].isin(selected_candidates)]

                for i, (_, row) in enumerate(sub_df.iterrows()):
                    name = get_field(row, ["name", "candidate_name"], "Candidate")
                    email = get_field(row, ["email", "mail"], "").strip()

                    if not email or "@" not in email:
                        failed_candidates.append(name)
                        continue

                    status.text(f"Sending ({i + 1}/{len(sub_df)}): {name}...")

                    email_body = f"""
                    <p>Hi {name},</p>
                    <p>Thank you for applying for <b>{current_role}</b>. Please complete your assessment at the link below:</p>
                    <p><a href="{test_link}">{test_link}</a></p>
                    <p>Best regards,<br>Hiring Team</p>
                    """

                    try:
                        send_email(email, f"Assessment Test - {current_role}", email_body)
                        sent_count += 1
                    except Exception:
                        failed_candidates.append(name)

                    time.sleep(0.2)
                    progress_bar.progress((i + 1) / len(sub_df))

                status.empty()
                st.success(f"Successfully dispatched {sent_count} assessment emails.")
                if failed_candidates:
                    st.warning(f"Could not send to: {', '.join(failed_candidates)}")
    else:
        st.info("Please complete Step 1 first.")


# --- TAB 3: SCORING & RANKING ---
with tab3:
    st.header("Step 3: Test Scores & Composite Ranking")
    test_file = st.file_uploader("Upload Test Results (CSV / Excel)", type=["csv", "xlsx"], key="test_file")

    if isinstance(st.session_state.evaluations, pd.DataFrame) and not st.session_state.evaluations.empty:
        eval_df = clean_dataframe(st.session_state.evaluations)

        if test_file:
            if test_file.name.endswith(".csv"):
                test_df = pd.read_csv(test_file)
            else:
                test_df = pd.read_excel(test_file)
            test_df = clean_dataframe(test_df)

            if "email" not in test_df.columns:
                mail_cols = [c for c in test_df.columns if "email" in c or "mail" in c]
                if mail_cols:
                    test_df.rename(columns={mail_cols[0]: "email"}, inplace=True)
        else:
            test_df = pd.DataFrame()
            st.info("Upload test scores to calculate combined composite rankings.")

        if not test_df.empty and "email" in eval_df.columns and "email" in test_df.columns:
            eval_df["email_clean"] = eval_df["email"].astype(str).str.strip().str.lower()
            test_df["email_clean"] = test_df["email"].astype(str).str.strip().str.lower()

            base_eval = eval_df.drop(columns=["test_la", "test_code"], errors="ignore")
            merged_df = pd.merge(base_eval, test_df[["email_clean", "test_la", "test_code"]], on="email_clean", how="left")

            code_scores = pd.to_numeric(merged_df.get("test_code", 0), errors="coerce").fillna(0)
            la_scores = pd.to_numeric(merged_df.get("test_la", 0), errors="coerce").fillna(0)

            score_col = "overall_score" if "overall_score" in merged_df.columns else "ai score"
            ai_scores = pd.to_numeric(merged_df.get(score_col, 0), errors="coerce").fillna(0)

            # Weighted composite calculation
            merged_df["composite_score"] = ((ai_scores * 0.40) + (code_scores * 0.35) + (la_scores * 0.25)).round(2)
            ranked_df = merged_df.sort_values(by="composite_score", ascending=False).reset_index(drop=True)

            st.session_state.final_ranked = ranked_df
            st.dataframe(ranked_df[["name", "email", "composite_score", score_col, "test_code", "test_la"]], use_container_width=True)
        else:
            eval_df["email_clean"] = eval_df["email"].astype(str).str.strip().str.lower()
            score_col = "overall_score" if "overall_score" in eval_df.columns else "ai score"
            eval_df["composite_score"] = pd.to_numeric(eval_df.get(score_col, 0), errors="coerce").fillna(0)
            ranked_df = eval_df.sort_values(by="composite_score", ascending=False).reset_index(drop=True)

            st.session_state.final_ranked = ranked_df
            st.dataframe(ranked_df[["name", "email", "composite_score"]], use_container_width=True)
    else:
        st.info("Please complete Step 1 first.")


# --- TAB 4: INTERVIEW SCHEDULER ---
with tab4:
    st.header("Step 4: Schedule Interviews & Send Invites")

    if st.session_state.final_ranked is not None and not st.session_state.final_ranked.empty:
        ranked_data = st.session_state.final_ranked.copy()

        if "email" not in ranked_data.columns:
            mail_cols = [c for c in ranked_data.columns if "email" in c or "mail" in c]
            ranked_data["email"] = ranked_data[mail_cols[0]] if mail_cols else "N/A"

        ranked_data["email"] = ranked_data["email"].astype(str).str.strip()
        valid_candidates = ranked_data[ranked_data["email"].str.lower() != "n/a"].reset_index(drop=True)

        if valid_candidates.empty:
            st.warning("No candidate emails found.")
        else:
            col1, col2 = st.columns(2)
            with col1:
                strategy = st.radio("Selection Strategy", ["Top N Candidates", "Custom Selection", "Single Candidate"], horizontal=True)
            with col2:
                limit_n = st.number_input("Top N Limit", min_value=1, max_value=len(valid_candidates), value=min(10, len(valid_candidates)))

            selected_candidates = []
            if strategy == "Top N Candidates":
                selected_candidates = valid_candidates.head(int(limit_n)).to_dict(orient="records")
                st.info(f"Selected top {len(selected_candidates)} ranked candidate(s).")
            elif strategy == "Custom Selection":
                all_emails = valid_candidates["email"].tolist()
                chosen_emails = st.multiselect("Choose Candidates", options=all_emails, default=all_emails[:min(30, len(all_emails))])
                selected_candidates = valid_candidates[valid_candidates["email"].isin(chosen_emails)].to_dict(orient="records")
            else:
                all_emails = valid_candidates["email"].tolist()
                single_email = st.selectbox("Choose Candidate", options=all_emails)
                if single_email:
                    selected_candidates = valid_candidates[valid_candidates["email"] == single_email].to_dict(orient="records")

            st.markdown("---")
            c1, c2, c3 = st.columns([1, 1, 1.5])
            with c1:
                start_iso = st.text_input("Start Time", "2026-07-25T11:00:00")
            with c2:
                end_iso = st.text_input("End Time", "2026-07-25T11:45:00")
            with c3:
                custom_meet_link = st.text_input("Google Meet URL", "https://meet.google.com/qcu-gewh-qth")

            role_name = role_title.strip() if role_title.strip() else "Position"
            desc_name = interview_desc.strip() if interview_desc.strip() else "Technical interview round."

            # Fast Multithreaded Dispatch
            if st.button(f"Send Interview Invites ({len(selected_candidates)})"):
                if not selected_candidates:
                    st.error("Please select at least one candidate.")
                else:
                    progress_bar = st.progress(0)
                    status_text = st.empty()
                    status_text.text("Sending interview invites in parallel...")

                    successful = 0
                    failed = []
                    total = len(selected_candidates)

                    with ThreadPoolExecutor(max_workers=5) as executor:
                        future_to_candidate = {
                            executor.submit(dispatch_interview_email, cand, role_name, desc_name, start_iso, end_iso, custom_meet_link): cand
                            for cand in selected_candidates
                        }

                        completed = 0
                        for future in as_completed(future_to_candidate):
                            is_ok, candidate_name, msg = future.result()
                            if is_ok:
                                successful += 1
                            else:
                                failed.append(f"{candidate_name} ({msg})")

                            completed += 1
                            progress_bar.progress(completed / total)

                    status_text.empty()
                    if successful > 0:
                        st.success(f"Successfully sent {successful}/{total} interview invites!")
                    if failed:
                        st.warning(f"Failed sending to {len(failed)} candidate(s): {', '.join(failed)}")
    else:
        st.info("Please complete Step 1 and Step 3 first.")