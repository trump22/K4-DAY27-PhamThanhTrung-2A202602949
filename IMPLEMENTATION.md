# Lab27 — implementation and execution status

Student: Pham Thanh Trung — 2A202602949

## Implementation

- Exercise 1: structured PR analysis, confidence routing and all terminal branches.
- Exercise 2: MemorySaver, approval interrupt, resume with the same thread.
- Exercise 3: diff-specific clarification questions, human answers, refined analysis and commit path.
- Exercise 4: structured SQLite events, durable checkpoints and reopening existing threads.
- Exercise 5: Streamlit approval/escalation cards, resume, saved-session selector and URL persistence.

The original `common/`, `audit/`, thresholds and assignment README are unchanged.
There are no supplied test files. No tests were modified.

## Details that affect correctness

1. Actual constants are `AUTO_APPROVE_THRESHOLD=0.73`, `ESCALATE_THRESHOLD=0.58`.
   Exactly 0.58 requests human approval; exactly 0.73 takes the automatic branch.
2. Confidence describes completeness/correctness of the review, not a calibrated safety probability.
   No PR-specific fixed confidence values are used.
3. Nodes containing `interrupt()` restart on resume. GitHub posting stays in a downstream node.
   The pending audit event is written again when the interrupt node replays, as specified by Exercise 4.
4. Reopening a SQLite thread restores its checkpoint rather than invoking the original input again.
5. The UI creates its asynchronous saver inside each event loop. URL-bound session selection
   restores a checkpoint even after the browser session state is lost.
6. Exercise 2's provided commit semantics are preserved: Approve posts; Reject/Edit stop without posting.
   Automatic rewrite on Edit is an optional bonus, not implemented.
7. The Vlearn Exercise 5 checkpoint and supplied graph resume escalation directly into synthesize/commit.
   The UI explicitly tells the reviewer that submitting answers posts the refined review.
   The README's mention of another final confirmation differs from this supplied flow.
8. The provided replay list uses lexical `MAX(risk_level)`, which can rank `med` above `high`.
   The UI uses an explicit numeric risk ranking; the supplied replay module remains unchanged.

## Verification on 2026-10-15

| Check | Result |
|---|---|
| Python 3.13, `uv sync` | Passed |
| Compile all exercise scripts and app | Passed |
| Graph construction for exercises 1–3 | Passed |
| Six routing boundary cases per exercise 1–3 | Passed, offline fixtures |
| MemorySaver interrupt/resume | Passed, offline rejection fixture, no network |
| SQLite interrupt persisted in one process, restored in another | Passed, separate offline database |
| Live SQLite audit | PR #1: 7 rows, including repeated pending event, reviewer approval and commit |
| Streamlit startup | Running locally on port 8527 |
| Live GitHub PR fetching | Passed for PR-Demo #1 and #2 |
| Live Gemini 3.5 Flash analysis | Gemini 3.5: HTTP 503 high demand; Gemini 2.5: HTTP 404 unavailable to new users; Gemini 3.8 completed both PR analyses |
| Exercise 1 live PR branches | PR #1: 0.68 human_approval; PR #2: 0.45 escalate (Gemini 3.8 Flash) |
| Exercise 2 live approval | 0.65, interrupt/resume, final_action=committed |
| Exercise 3 live escalation | 0.52, three user answers, synthesize to 0.80, committed_after_escalation |
| Exercise 4/5 live UI | PR #1 approval and PR #2 escalation both committed; SQLite persisted across processes; browser reload restored waiting card |
| Reject/Edit behavior | Both rejected without posting when replaying the saved real 0.65 analysis; no new LLM call |
| Final Vlearn submission | Pending complete live evidence |

Offline diagnostics are not claimed as real PR reviews or human responses. Their database and scripts
are outside the submission repository. The initial provider failure is not a successful review.

## Run

Copy `.env.example` to `.env` and configure the provider plus GitHub token and username.
Never commit `.env` or SQLite databases. The existing factory accepts an OpenAI-compatible provider;
its historical `OPENROUTER_API_KEY` variable also holds the Google key when using Google's compatible endpoint.

```powershell
uv sync
$env:PYTHONUTF8 = '1'
uv run python exercises/exercise_1_confidence.py --pr https://github.com/VinUni-AI20k/PR-Demo/pull/1
uv run python exercises/exercise_2_hitl.py --pr https://github.com/VinUni-AI20k/PR-Demo/pull/1
uv run python exercises/exercise_3_escalation.py --pr https://github.com/VinUni-AI20k/PR-Demo/pull/2
uv run python exercises/exercise_4_audit.py --pr https://github.com/VinUni-AI20k/PR-Demo/pull/1
uv run python -m audit.replay --list
uv run python -m audit.replay --thread <thread-id>
uv run streamlit run app.py
```

For a durable interrupted session, repeat Exercise 4 with `--thread <existing-id>`.
The UI uses Streamlit 1.66 query-parameter binding for reload persistence; the dependency floor
and committed lockfile match that API.

## Live evidence

The final workflow used `gemini-3.5-flash-lite` through Google's OpenAI-compatible endpoint,
with optional reasoning_effort=low and a 90-second per-request timeout. `common.llm` is unchanged.

- Exercise 2: https://github.com/VinUni-AI20k/PR-Demo/pull/1#issuecomment-6195950821
- Exercise 3: https://github.com/VinUni-AI20k/PR-Demo/pull/2#issuecomment-6196044152
- Exercise 4/5 approval: https://github.com/VinUni-AI20k/PR-Demo/pull/1#issuecomment-6196048890
- Exercise 4/5 escalation: https://github.com/VinUni-AI20k/PR-Demo/pull/2#issuecomment-6196089740

Live SQLite thread IDs: `lab27-live-pr1` and `08824edc-c69a-45c1-98a8-35c73640103f`.
Reviewer requirements supplied by the user: HTTPS in production, bcrypt, server-authenticated sessions/user IDs.
Additional migration/permission requirements not supplied by the reviewer were explicitly marked unconfirmed.

## Observed limitations

- Gemini 3.5 Flash returned 503 high-demand errors. Gemini 2.5 Flash returned 404 (not available to new users).
- Gemini 3.8 completed both Exercise 1 analyses, then returned a **429 daily free-tier quota** error
  (20 requests/project/model/day, retry delay about 8h25m). Calls to that exhausted model were stopped.
  An earlier 503 alone did not establish quota exhaustion.
- Self-reported confidence varies. A later fresh PR #1 analysis returned 0.85 and went to the automatic branch,
  so that particular attempt did not exercise rejection. Its pre-post pause prevented an extra comment.
  The rejection/edit checks therefore explicitly replayed the previously saved real 0.65 analysis.
  Scores were never overwritten and thresholds were not changed to make an experiment pass.
- The API results and branch checks do not establish production reliability or calibrated probabilities.

LangGraph currently warns when deserializing the custom PRAnalysis type; the diagnostic restored it
successfully, but a future stricter serializer will require registering that type explicitly.
