"""Exercise 5 — Streamlit approval UI for the HITL PR review agent.

Run with:
    uv run streamlit run app.py

Goal: wrap the LangGraph built in exercises 1–4 in a web UI that adapts to
the confidence bucket of each PR.

Routing thresholds (common/schemas.py):
    >= 73%       auto_approve     UI shows a success card; reviewer does nothing
    58% <= c <73% human_approval  UI shows Approve / Reject / Edit buttons
    <  58%       escalate         UI shows a question form for the reviewer
"""

from __future__ import annotations

import asyncio
import uuid

import streamlit as st
from dotenv import load_dotenv
from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.types import Command

from common.db import db_path, db_conn
from exercises.exercise_4_audit import build_graph
from exercises.review_logic import validate_answers


load_dotenv()


# ─── Session state ─────────────────────────────────────────────────────────
if "thread_id" not in st.session_state:
    st.session_state.thread_id = None
if "pr_url" not in st.session_state:
    st.session_state.pr_url = ""
if "interrupt_payload" not in st.session_state:
    st.session_state.interrupt_payload = None
if "final" not in st.session_state:
    st.session_state.final = None


# ─── Page setup ────────────────────────────────────────────────────────────
st.set_page_config(page_title="HITL PR Review", layout="wide")
st.title("HITL PR Review Agent")


# ─── Sidebar — recent sessions ─────────────────────────────────────────────
with st.sidebar:
    st.header("Recent sessions")
    async def recent_sessions():
        async with db_conn() as conn:
            async with conn.execute("""
                SELECT thread_id, pr_url, MAX(timestamp) AS last_event,
                  CASE MAX(CASE risk_level WHEN 'high' THEN 3 WHEN 'med' THEN 2 ELSE 1 END)
                    WHEN 3 THEN 'high' WHEN 2 THEN 'med' ELSE 'low' END AS worst_risk
                FROM audit_events GROUP BY thread_id, pr_url ORDER BY last_event DESC LIMIT 30
            """) as cur:
                return [dict(row) for row in await cur.fetchall()]
    sessions = asyncio.run(recent_sessions())
    if st.session_state.get("select_after_run"):
        st.session_state.saved_thread = st.session_state.pop("select_after_run")
    by_id = {row['thread_id']: row for row in sessions}
    selected_thread = st.selectbox("Saved session", [""] + list(by_id),
        key="saved_thread", bind="query-params",
        format_func=lambda tid: "New review" if not tid else f"{tid[:8]} · {by_id[tid]['worst_risk']}")
    if selected_thread:
        st.caption(by_id[selected_thread]['pr_url'])
        st.caption("Last event: " + by_id[selected_thread]['last_event'])


# ─── Renderers per interrupt kind ──────────────────────────────────────────
def render_approval_card(payload: dict) -> dict | None:
    """58% <= confidence <73%: show review and three approval choices."""
    conf = payload["confidence"]
    st.subheader(f"Approval requested — confidence {conf:.0%}")
    st.caption(payload["confidence_reasoning"])
    st.markdown(payload["summary"])

    for c in payload.get("comments", []):
        st.markdown(f"- **[{c['severity']}]** `{c['file']}:{c.get('line') or '?'}` — {c['body']}")

    with st.expander("Diff"):
        st.code(payload.get("diff_preview", ""), language="diff")

    feedback = st.text_input("Feedback (optional)", key=f"approval_feedback_{st.session_state.thread_id}")
    st.caption("Approve posts the review. Reject and Edit stop without posting, as in Exercise 2.")
    col1, col2, col3 = st.columns(3)
    if col1.button("Approve", type="primary"):
        return {"choice": "approve", "feedback": feedback}
    if col2.button("Reject"):
        return {"choice": "reject", "feedback": feedback}
    if col3.button("Edit"):
        return {"choice": "edit", "feedback": feedback}
    return None


def render_escalation_card(payload: dict) -> dict | None:
    """< 58% bucket: show risk factors + question form. Return {question: answer} or None."""
    conf = payload["confidence"]
    st.subheader(f"Strong escalation — confidence {conf:.0%}")
    st.caption(payload["confidence_reasoning"])
    if payload.get("risk_factors"):
        st.error("Risks: " + ", ".join(payload["risk_factors"]))
    st.markdown(payload["summary"])

    with st.form("escalation"):
        answers = {q: st.text_area(q, key=f"answer_{st.session_state.thread_id}_{i}")
                   for i, q in enumerate(payload["questions"])}
        st.caption("Submitting resumes the graph and posts the refined review to GitHub.")
        if st.form_submit_button("Submit answers"):
            try:
                return validate_answers(answers, payload["questions"])
            except ValueError as exc:
                st.error(str(exc))
    return None


# ─── Drive the graph ───────────────────────────────────────────────────────
async def run_graph(pr_url: str, thread_id: str, resume_value=None, *, restore_only=False):
    """Invoke the graph once. Returns the final result or {'__interrupt__': ...}."""
    async with AsyncSqliteSaver.from_conn_string(db_path()) as cp:
        await cp.setup()
        cfg = {"configurable": {"thread_id": thread_id}}

        app = build_graph(cp)
        snapshot = await app.aget_state(cfg)
        if snapshot.values:
            if pr_url and snapshot.values.get("pr_url") != pr_url:
                raise ValueError("Thread belongs to another PR")
            if resume_value is not None:
                if not any(task.interrupts for task in snapshot.tasks):
                    raise ValueError("Session is no longer waiting for input")
                return await app.ainvoke(Command(resume=resume_value), cfg)
            result = dict(snapshot.values)
            pending = [i for task in snapshot.tasks for i in task.interrupts]
            if pending:
                result["__interrupt__"] = pending
            elif snapshot.next and not restore_only:
                return await app.ainvoke(None, cfg)
            return result
        if restore_only:
            raise ValueError("No saved checkpoint for this thread")
        return await app.ainvoke({"pr_url": pr_url, "thread_id": thread_id}, cfg)


if selected_thread and selected_thread != st.session_state.thread_id:
    result = asyncio.run(run_graph("", selected_thread, restore_only=True))
    st.session_state.thread_id = selected_thread
    st.session_state.pr_url = result.get("pr_url", "")
    pending = result.get("__interrupt__")
    st.session_state.interrupt_payload = pending[0].value if pending else None
    st.session_state.final = None if pending else result


# ─── Main flow ─────────────────────────────────────────────────────────────
with st.form("start"):
    pr_url = st.text_input(
        "PR URL", value=st.session_state.pr_url,
        placeholder="https://github.com/VinUni-AI20k/PR-Demo/pull/1",
    )
    st.caption("High confidence reviews post automatically. Use a repository you may review.")
    submitted = st.form_submit_button("Run review")

def invoke_ui(pr_url, thread_id, resume_value=None, *, restore_only=False):
    try:
        return asyncio.run(run_graph(pr_url, thread_id, resume_value, restore_only=restore_only))
    except Exception as exc:
        # A failed request leaves SQLite checkpoints available for a later retry.
        st.error(f"{type(exc).__name__}: {exc}")
        st.caption("The saved session can be reopened from Recent sessions.")
        st.stop()

if submitted and pr_url:
    st.session_state.pr_url = pr_url
    st.session_state.thread_id = str(uuid.uuid4())
    st.session_state.interrupt_payload = None
    st.session_state.final = None

    with st.spinner("Fetching PR + asking the LLM..."):
        result = invoke_ui(pr_url, st.session_state.thread_id)

    if "__interrupt__" in result:
        st.session_state.interrupt_payload = result["__interrupt__"][0].value
    else:
        st.session_state.final = result
    st.session_state.select_after_run = st.session_state.thread_id
    st.rerun()

# Render the current interrupt card, if any
payload = st.session_state.interrupt_payload
if payload is not None:
    kind = payload["kind"]
    answer = render_approval_card(payload) if kind == "approval_request" else render_escalation_card(payload)
    if answer is not None:
        with st.spinner("Resuming..."):
            result = invoke_ui(
                st.session_state.pr_url, st.session_state.thread_id, resume_value=answer,
            )
        if "__interrupt__" in result:
            st.session_state.interrupt_payload = result["__interrupt__"][0].value
        else:
            st.session_state.interrupt_payload = None
            st.session_state.final = result
        st.rerun()

# Render final state, if reached
if st.session_state.final is not None:
    final = st.session_state.final
    action = final.get("final_action", "?")
    if action in {"auto_committed", "committed", "committed_after_escalation"}:
        st.success(f"✓ {action} — comment posted to {st.session_state.pr_url}")
        st.link_button("View comment on GitHub", st.session_state.pr_url + "#discussion_bucket")
    elif action == "rejected":
        st.warning("Rejected — no comment posted")
    elif "failed" in action:
        st.error(f"Posting failed: {action}")
    else:
        st.info(f"final_action = {action}")
        if st.button("Continue saved review"):
            with st.spinner("Continuing from the saved checkpoint..."):
                result = invoke_ui(st.session_state.pr_url, st.session_state.thread_id)
            pending = result.get("__interrupt__")
            st.session_state.interrupt_payload = pending[0].value if pending else None
            st.session_state.final = None if pending else result
            st.rerun()
    analysis = final.get("analysis")
    if analysis:
        st.metric("Confidence", f"{analysis.confidence:.0%}")
        st.markdown(analysis.summary)
    st.caption(f"thread_id = {st.session_state.thread_id}  ·  replay: "
               f"`uv run python -m audit.replay --thread {st.session_state.thread_id}`")
