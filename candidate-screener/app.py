import html
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime
from typing import Any

import pandas as pd
import streamlit as st
from dotenv import load_dotenv

from services.ai_evaluator import evaluate_candidate_with_ai
from services.email_service import send_email
from services.github_service import analyze_github_profile
from services.resume_service import download_and_extract_resume

load_dotenv()

st.set_page_config(
    page_title="Candidate Screener & Scheduler",
    page_icon="📋",
    layout="wide",
)

EMAIL_REGEX = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


# ─── Session State ────────────────────────────────────────────────────────────
def init_session_state() -> None:
    defaults: dict[str, Any] = {
        "candidates_df": None,
        "evaluations": pd.DataFrame(),
        "final_ranked": pd.DataFrame(),
    }
    for key, default_val in defaults.items():
        if key not in st.session_state:
            st.session_state[key] = default_val


init_session_state()


# ─── Helper Utilities ─────────────────────────────────────────────────────────
def is_valid_email(email: str) -> bool:
    return bool(email and EMAIL_REGEX.match(email.strip()))


def get_field(row: pd.Series, possible_keys: list[str], default_val: str = "") -> str:
    """Extract the first non-empty string matching any alias in possible_keys."""
    for key in possible_keys:
        if key in row and pd.notna(row[key]):
            val = str(row[key]).strip()
            if val and val.lower() != "nan":
                return val
    return default_val


def clean_dataframe(df: pd.DataFrame | None) -> pd.DataFrame:
    """Normalize column names by stripping whitespace and lowercasing."""
    if df is None or df.empty:
        return pd.DataFrame()
    cleaned = df.copy()
    cleaned.columns = cleaned.columns.str.strip().str.lower()
    return cleaned


def resolve_column(df: pd.DataFrame, candidates: list[str]) -> str | None:
    """Return the first matching column name present in df."""
    for col in candidates:
        if col in df.columns:
            return col
    return None


@st.cache_data(show_spinner=False)
def load_uploaded_table(file_bytes: bytes, file_name: str) -> pd.DataFrame:
    """Cache parsed CSV/Excel uploads to avoid re-reading on every rerun."""
    from io import BytesIO

    buffer = BytesIO(file_bytes)
    if file_name.lower().endswith(".csv"):
        return pd.read_csv(buffer)
    return pd.read_excel(buffer)


def evaluate_single_candidate(
    index: int, row: pd.Series, role: str, job_desc: str
) -> dict[str, Any]:
    """Fetch candidate resume/GitHub context and run AI evaluation."""
    name = get_field(row, ["name", "candidate_name", "full_name"], f"Candidate {index + 1}")
    email = get_field(row, ["email", "email_address", "mail"], "")

    resume_url = get_field(row, ["resume", "resume_link", "pdf"], "")
    resume_text = (
        download_and_extract_resume(resume_url) if resume_url else "No resume provided"
    )

    github_url = get_field(row, ["github", "github_link", "profile"], "")
    github_info = (
        analyze_github_profile(github_url) if github_url else "No GitHub link provided"
    )

    context_jd = f"Role: {role}\nDescription: {job_desc}" if role else job_desc
    ai_result = evaluate_candidate_with_ai(
        row.to_dict(), resume_text, github_info, context_jd
    )

    output = row.to_dict()
    output.update(
        {
            "name": name,
            "email": email,
            "github_summary": github_info,
            **(ai_result or {}),
        }
    )
    return output


def dispatch_interview_email(
    candidate: dict[str, Any],
    role: str,
    description: str,
    start_time: str,
    end_time: str,
    meet_link: str,
) -> tuple[bool, str, str]:
    """Send a single XSS-safe interview invitation email."""
    name = str(candidate.get("name", "Candidate")).strip() or "Candidate"
    email = str(candidate.get("email", "")).strip()

    if not is_valid_email(email):
        return False, name, "Invalid or missing email"

    safe_name = html.escape(name)
    safe_role = html.escape(role)
    safe_desc = html.escape(description).replace("\n", "<br>")
    safe_time = html.escape(f"{start_time} – {end_time}")
    safe_link = html.escape(meet_link.strip(), quote=True)

    email_body = f"""
    <div style="font-family: Arial, sans-serif; line-height: 1.6; color: #1f2937;">
      <p>Hi {safe_name},</p>
      <p>Congratulations! We would like to invite you to interview for the <b>{safe_role}</b> role.</p>
      <p><b>Interview Details:</b><br>{safe_desc}</p>
      <p><b>Scheduled Time:</b> {safe_time}</p>
      <p><b>Meeting Link:</b> <a href="{safe_link}">{safe_link}</a></p>
      <p>Best regards,<br>Hiring Team</p>
    </div>
    """

    try:
        send_email(email, f"Interview Invitation - {role}", email_body)
        return True, name, email
    except Exception as err:
        return False, name, str(err)


# ─── Sidebar Controls ─────────────────────────────────────────────────────────
st.title("Candidate Screening & Interview Platform")
st.caption("Evaluate applicants, verify GitHub profiles, rank candidates, and schedule interviews.")

with st.sidebar:
    st.header("Control Panel")
    role_title = st.text_input(
        "Job Role Title", value="", placeholder="e.g. Full Stack AI Engineer"
    ).strip()
    jd_text = st.text_area(
        "Job Description",
        height=160,
        value="",
        placeholder="Paste job description and required skills here...",
    ).strip()
    interview_desc = st.text_area(
        "Interview Details",
        height=140,
        value="",
        placeholder="Enter interview format, panel details, and expectations...",
    ).strip()

tab1, tab2, tab3, tab4 = st.tabs(
    [
        "1. Applicant Evaluation",
        "2. Assessment Dispatch",
        "3. Test Scoring & Ranking",
        "4. Interview Scheduler",
    ]
)

# ─── TAB 1: APPLICANT EVALUATION ──────────────────────────────────────────────
with tab1:
    st.header("Step 1: Upload Candidates & Evaluate")
    uploaded_file = st.file_uploader(
        "Upload Candidates (CSV / Excel)", type=["csv", "xlsx"]
    )

    if uploaded_file:
        data = load_uploaded_table(uploaded_file.getvalue(), uploaded_file.name)
        st.session_state.candidates_df = data
        st.dataframe(data.head(5), use_container_width=True)

        col_btn, col_workers = st.columns([2, 1])
        with col_workers:
            max_workers = st.number_input("Parallel Workers", min_value=1, max_value=8, value=4)
        with col_btn:
            st.write("")
            start_eval = st.button("Start AI Evaluation", type="primary", use_container_width=True)

        if start_eval:
            if not jd_text:
                st.warning("Please fill in the Job Description in the sidebar first.")
            elif data.empty:
                st.warning("The uploaded file has no rows to evaluate.")
            else:
                progress_bar = st.progress(0)
                status = st.empty()
                total_rows = len(data)
                results: list[dict[str, Any] | None] = [None] * total_rows
                errors: list[str] = []

                with ThreadPoolExecutor(max_workers=int(max_workers)) as executor:
                    futures_map = {
                        executor.submit(
                            evaluate_single_candidate, idx, row, role_title, jd_text
                        ): idx
                        for idx, row in data.iterrows()
                    }

                    for completed, future in enumerate(as_completed(futures_map), start=1):
                        idx = futures_map[future]
                        try:
                            results[idx] = future.result()
                        except Exception as exc:
                            errors.append(f"Row {idx + 1}: {exc}")
                        status.text(f"Evaluated {completed}/{total_rows} candidates...")
                        progress_bar.progress(completed / total_rows)

                status.empty()
                valid_results = [r for r in results if r is not None]
                eval_df = pd.DataFrame(valid_results)
                st.session_state.evaluations = eval_df
                st.session_state.final_ranked = eval_df.copy()

                st.success(f"Evaluated {len(valid_results)}/{total_rows} candidates.")
                if errors:
                    with st.expander(f"View {len(errors)} evaluation error(s)"):
                        for err in errors:
                            st.error(err)

    if not st.session_state.evaluations.empty:
        st.subheader("Evaluation Leaderboard")
        eval_df = clean_dataframe(st.session_state.evaluations)
        score_col = resolve_column(eval_df, ["overall_score", "ai score", "score"])
        if score_col:
            eval_df = eval_df.sort_values(by=score_col, ascending=False).reset_index(drop=True)

        preferred_cols = [
            "name",
            "email",
            score_col,
            "jd_relevance_score",
            "github_score",
            "reasoning",
        ]
        display_cols = [c for c in preferred_cols if c and c in eval_df.columns]
        st.dataframe(
            eval_df[display_cols] if display_cols else eval_df,
            use_container_width=True,
        )
        st.download_button(
            "Download Evaluation CSV",
            data=eval_df.to_csv(index=False).encode("utf-8"),
            file_name="candidate_evaluations.csv",
            mime="text/csv",
        )


# ─── TAB 2: DISPATCH ASSESSMENTS ──────────────────────────────────────────────
with tab2:
    st.header("Step 2: Dispatch Online Assessment")

    if st.session_state.evaluations.empty:
        st.info("Complete Step 1 first to load evaluated candidates.")
    else:
        eval_df = clean_dataframe(st.session_state.evaluations)
        email_col = resolve_column(eval_df, ["email", "email_address", "mail"])
        name_col = resolve_column(eval_df, ["name", "candidate_name", "full_name"])

        eval_df["resolved_email"] = eval_df[email_col].fillna("").astype(str).str.strip() if email_col else ""
        eval_df["resolved_name"] = (
            eval_df[name_col].fillna("").astype(str).str.strip()
            if name_col
            else [f"Candidate {i + 1}" for i in range(len(eval_df))]
        )
        eval_df["label"] = eval_df.apply(
            lambda r: f"{r['resolved_name']} ({r['resolved_email']})"
            if r["resolved_email"]
            else r["resolved_name"],
            axis=1,
        )

        candidate_options = eval_df["label"].tolist()
        selected_candidates = st.multiselect(
            "Select Candidates for Assessment",
            options=candidate_options,
            default=candidate_options,
        )
        test_link = st.text_input(
            "Assessment Link", placeholder="https://forms.gle/your-assessment-link"
        ).strip()
        current_role = role_title or "the open position"

        if st.button(f"Dispatch Assessment Emails ({len(selected_candidates)})", type="primary"):
            if not selected_candidates:
                st.warning("Please select at least one candidate.")
            elif not test_link.startswith(("http://", "https://")):
                st.warning("Please enter a valid http(s) assessment link.")
            else:
                sub_df = eval_df[eval_df["label"].isin(selected_candidates)]
                progress_bar = st.progress(0)
                status = st.empty()
                sent_count = 0
                failed_candidates: list[str] = []

                safe_role = html.escape(current_role)
                safe_link = html.escape(test_link, quote=True)

                for idx, (_, row) in enumerate(sub_df.iterrows(), start=1):
                    name = row["resolved_name"] or "Candidate"
                    email = row["resolved_email"]

                    if not is_valid_email(email):
                        failed_candidates.append(f"{name} (invalid email)")
                        progress_bar.progress(idx / len(sub_df))
                        continue

                    status.text(f"Sending ({idx}/{len(sub_df)}): {name}...")
                    email_body = f"""
                    <div style="font-family: Arial, sans-serif; line-height: 1.6; color: #1f2937;">
                      <p>Hi {html.escape(name)},</p>
                      <p>Thank you for applying for the <b>{safe_role}</b> role. Please complete your online assessment using the link below:</p>
                      <p><a href="{safe_link}">{safe_link}</a></p>
                      <p>Best regards,<br>Hiring Team</p>
                    </div>
                    """
                    try:
                        send_email(email, f"Assessment Invitation - {current_role}", email_body)
                        sent_count += 1
                    except Exception as exc:
                        failed_candidates.append(f"{name} ({exc})")

                    progress_bar.progress(idx / len(sub_df))

                status.empty()
                st.success(f"Dispatched {sent_count}/{len(sub_df)} assessment emails.")
                if failed_candidates:
                    st.warning(f"Failed deliveries: {', '.join(failed_candidates)}")


# ─── TAB 3: TEST SCORING & RANKING ────────────────────────────────────────────
with tab3:
    st.header("Step 3: Test Scores & Composite Ranking")

    if st.session_state.evaluations.empty:
        st.info("Complete Step 1 first before calculating rankings.")
    else:
        eval_df = clean_dataframe(st.session_state.evaluations)
        score_col = resolve_column(eval_df, ["overall_score", "ai score", "score"])

        c_w1, c_w2, c_w3 = st.columns(3)
        with c_w1:
            w_ai = st.slider("AI Evaluation Weight", 0.0, 1.0, 0.40, 0.05)
        with c_w2:
            w_code = st.slider("Coding Test Weight", 0.0, 1.0, 0.35, 0.05)
        with c_w3:
            w_la = st.slider("Aptitude / LA Weight", 0.0, 1.0, 0.25, 0.05)

        test_file = st.file_uploader(
            "Upload Test Results (CSV / Excel)", type=["csv", "xlsx"], key="test_file"
        )

        if test_file:
            test_df = clean_dataframe(
                load_uploaded_table(test_file.getvalue(), test_file.name)
            )
            test_email_col = resolve_column(test_df, ["email", "email_address", "mail"])
            eval_email_col = resolve_column(eval_df, ["email", "email_address", "mail"])

            if test_email_col and eval_email_col:
                eval_df["email_clean"] = eval_df[eval_email_col].astype(str).str.strip().str.lower()
                test_df["email_clean"] = test_df[test_email_col].astype(str).str.strip().str.lower()

                for col in ["test_code", "test_la"]:
                    if col not in test_df.columns:
                        test_df[col] = 0.0

                base_eval = eval_df.drop(columns=["test_la", "test_code"], errors="ignore")
                merged_df = pd.merge(
                    base_eval,
                    test_df[["email_clean", "test_la", "test_code"]].drop_duplicates("email_clean"),
                    on="email_clean",
                    how="left",
                )
                ai_scores = pd.to_numeric(merged_df.get(score_col, 0), errors="coerce").fillna(0)
                code_scores = pd.to_numeric(merged_df["test_code"], errors="coerce").fillna(0)
                la_scores = pd.to_numeric(merged_df["test_la"], errors="coerce").fillna(0)

                merged_df["composite_score"] = (
                    (ai_scores * w_ai) + (code_scores * w_code) + (la_scores * w_la)
                ).round(2)
                ranked_df = merged_df.sort_values(by="composite_score", ascending=False).reset_index(drop=True)
            else:
                st.warning("Could not match 'email' columns across files; falling back to AI scores.")
                eval_df["composite_score"] = pd.to_numeric(
                    eval_df.get(score_col, 0), errors="coerce"
                ).fillna(0)
                ranked_df = eval_df.sort_values(by="composite_score", ascending=False).reset_index(drop=True)
        else:
            st.info("Upload test scores above to blend test results, or proceed with AI-only rankings.")
            eval_df["composite_score"] = pd.to_numeric(
                eval_df.get(score_col, 0), errors="coerce"
            ).fillna(0)
            ranked_df = eval_df.sort_values(by="composite_score", ascending=False).reset_index(drop=True)

        st.session_state.final_ranked = ranked_df
        display_cols = [
            c
            for c in ["name", "email", "composite_score", score_col, "test_code", "test_la"]
            if c and c in ranked_df.columns
        ]
        st.dataframe(ranked_df[display_cols] if display_cols else ranked_df, use_container_width=True)
        st.download_button(
            "Download Final Ranked CSV",
            data=ranked_df.to_csv(index=False).encode("utf-8"),
            file_name="final_ranked_candidates.csv",
            mime="text/csv",
        )


# ─── TAB 4: INTERVIEW SCHEDULER ───────────────────────────────────────────────
with tab4:
    st.header("Step 4: Schedule Interviews & Send Invites")

    if st.session_state.final_ranked.empty:
        st.info("Complete Step 1 (and optionally Step 3) first.")
    else:
        ranked_data = clean_dataframe(st.session_state.final_ranked)
        email_col = resolve_column(ranked_data, ["email", "email_address", "mail"])

        if not email_col:
            st.warning("No email column found in candidate records.")
        else:
            ranked_data["email"] = ranked_data[email_col].fillna("").astype(str).str.strip()
            valid_candidates = ranked_data[ranked_data["email"].apply(is_valid_email)].reset_index(drop=True)

            if valid_candidates.empty:
                st.warning("No candidates with valid email addresses found.")
            else:
                col1, col2 = st.columns(2)
                with col1:
                    strategy = st.radio(
                        "Selection Strategy",
                        ["Top N Candidates", "Custom Selection", "Single Candidate"],
                        horizontal=True,
                    )
                with col2:
                    limit_n = st.number_input(
                        "Top N Limit",
                        min_value=1,
                        max_value=len(valid_candidates),
                        value=min(10, len(valid_candidates)),
                    )

                all_emails = valid_candidates["email"].tolist()
                selected_candidates: list[dict[str, Any]] = []

                if strategy == "Top N Candidates":
                    selected_candidates = valid_candidates.head(int(limit_n)).to_dict(orient="records")
                    st.info(f"Selected top {len(selected_candidates)} ranked candidate(s).")
                elif strategy == "Custom Selection":
                    chosen_emails = st.multiselect(
                        "Choose Candidates",
                        options=all_emails,
                        default=all_emails[: min(10, len(all_emails))],
                    )
                    selected_candidates = valid_candidates[
                        valid_candidates["email"].isin(chosen_emails)
                    ].to_dict(orient="records")
                else:
                    single_email = st.selectbox("Choose Candidate", options=all_emails)
                    if single_email:
                        selected_candidates = valid_candidates[
                            valid_candidates["email"] == single_email
                        ].to_dict(orient="records")

                st.markdown("---")
                c1, c2, c3 = st.columns([1, 1, 1.5])
                with c1:
                    start_iso = st.text_input("Start Time (ISO)", "2026-11-25T11:00:00").strip()
                with c2:
                    end_iso = st.text_input("End Time (ISO)", "2026-11-25T11:45:00").strip()
                with c3:
                    custom_meet_link = st.text_input(
                        "Google Meet / Video URL", placeholder="https://meet.google.com/xxx-xxxx-xxx"
                    ).strip()

                role_name = role_title or "Open Position"
                desc_name = interview_desc or "Technical interview round."

                if st.button(f"Send Interview Invites ({len(selected_candidates)})", type="primary"):
                    if not selected_candidates:
                        st.error("Please select at least one candidate.")
                    elif not custom_meet_link.startswith(("http://", "https://")):
                        st.error("Please provide a valid meeting URL before sending invites.")
                    else:
                        try:
                            datetime.fromisoformat(start_iso)
                            datetime.fromisoformat(end_iso)
                        except ValueError:
                            st.error("Start and End times must be valid ISO timestamps (YYYY-MM-DDTHH:MM:SS).")
                            st.stop()

                        progress_bar = st.progress(0)
                        status_text = st.empty()
                        status_text.text("Sending interview invites in parallel...")
                        successful = 0
                        failed: list[str] = []
                        total = len(selected_candidates)

                        with ThreadPoolExecutor(max_workers=5) as executor:
                            futures = [
                                executor.submit(
                                    dispatch_interview_email,
                                    cand,
                                    role_name,
                                    desc_name,
                                    start_iso,
                                    end_iso,
                                    custom_meet_link,
                                )
                                for cand in selected_candidates
                            ]

                            for completed, future in enumerate(as_completed(futures), start=1):
                                is_ok, candidate_name, msg = future.result()
                                if is_ok:
                                    successful += 1
                                else:
                                    failed.append(f"{candidate_name} ({msg})")
                                progress_bar.progress(completed / total)

                        status_text.empty()
                        if successful > 0:
                            st.success(f"Sent {successful}/{total} interview invites!")
                        if failed:
                            st.warning(f"Failed for {len(failed)} candidate(s): {', '.join(failed)}")
