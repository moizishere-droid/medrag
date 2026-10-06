# Phase 21: chat UI and login follow-up

Date: 2026-10-06. Supplements the original Phase 21 audit and its artifacts.

## Changes

- Login/register sets an HttpOnly, SameSite=Lax cookie with the token's lifetime
  (24 hours by default). Streamlit restores the token from its connection cookie
  after refresh. Sign-out removes the cookie and revokes its database token.
  Expired/invalid cookies cannot restore access; rejected cookies are ignored for
  the current Streamlit connection to prevent an endless rerun loop. Explicit
  bearer headers take precedence. Cookie-authenticated writes reject untrusted
  browser origins. No token is stored in localStorage or a URL.
- The browser component performs login/register/logout against the API so the
  browser receives the cookie; the component then reconnects Streamlit. API and
  UI must use the same hostname. Local ports 8501/8502 are allowed by default;
  configure `CORS_ORIGINS` for other ports. `MEDRAG_API_URL` and
  `MEDRAG_BROWSER_API_URL` separate server and browser addresses. HTTPS hosting
  requires `AUTH_COOKIE_SECURE=true` and a shared hostname/reverse proxy.
- Untitled sessions display `New Chat`. The first successful question names the
  session in the same locked transaction as messages/citations. "What is type 2
  diabetes?" becomes "Diabetes Type 2". Titles use deterministic normalization
  (8 words/80 characters), avoiding another paid model request. Later turns and
  explicit titles are preserved. Failed turns roll back the title too.
- The question is rendered before the blocking answer request; Thinking appears
  in the assistant message. Citation source entries group chunks by document
  ID/URL and keep all original answer markers. Different document IDs with the
  same filename remain separate. Historical citations without IDs fall back to
  title. Public health/config checks are cached for 30 seconds per connection;
  private sessions/history/evidence are not cached.
- Local BM25 and cross-encoder models warm at startup, with guarded single
  cross-encoder construction. Per-stage timings identify retrieval/generation
  delays without logging user questions. No answer/evidence cache crosses users.

## Verification

- Full default suite: 298 passed (`audit/ui_followup_unit.xml`); full real-service
  integration suite: 49 passed (`audit/ui_followup_integration.xml`). The affected auth/lifespan checks also passed
  after the final origin/warmup changes (14 passed). PostgreSQL tests use
  `medrag_chat_test`, Qdrant uses disposable
  collections, and Neo4j is queried read-only.
- Browser verification used isolated ports 8003/8503 and an isolated test account
  in the test database. Login succeeded; refresh remained signed in. During a
  four-second simulated answer, the question and Thinking were both visible.
  The answer updated the session selector to Diabetes Type 2 and showed one
  source entry for markers [1], [2]. Sign-out returned to the login form.
  Generation/evidence in this browser fixture were simulated; this is not a
  live medical-answer quality or PDF-upload test.
- The screenshot `audit/phase21_chat_ui.png` shows the simulated final UI. Its
  fixture deliberately uses the generic Uploaded document title.
- The project artifact inventory was rerun: 501 tracked-workspace files checked,
  no consistency issues and no saved notebook error outputs.
- A neutral real-model request measured warm retrieval at 15.137 seconds and
  generation at 2.930 seconds. Local short-input reranking measured cold 3.195
  seconds versus warm 0.135 seconds. A separate 20-full-chunk CPU benchmark took
  10.902 seconds at the default four threads; reducing to one thread worsened it
  to 17.455 seconds with unchanged top-five ranking. Thread settings were not
  changed. Warmup removes first-request loading, but sustained CPU/cloud latency
  remains a performance limit; faster hosting/inference should be benchmarked
  before promising a response-time target. One live embedding/answer call was
  performed in this follow-up; the earlier audit's unrun-work list is historical.

## Additional rerun, language and topic-panel fixes

- The installed Streamlit selectbox serializes displayed labels, even when its
  Python options are stable IDs. Duplicate `New Chat` labels were reproduced in
  the browser switching to another empty session on submission. Duplicate names
  now get simple numbered suffixes. A callback saves each submitted question
  and its session before sidebar/history reruns; pending questions pin selection
  to that session and are processed once. The first question also provides a
  provisional topic label while the successful backend transaction persists it.
- Intermittent real API disconnects were reproduced through `localhost` while
  direct `127.0.0.1` requests succeeded. Server requests now default to IPv4;
  browser auth stays on `localhost` for cookie sharing. Safe GET requests retry
  interrupted connections three times. Chat, upload and creation writes are
  never automatically replayed. On a failed session read, the UI retains the
  same account's last known list, offers Retry loading chats, and does not claim
  that there are no sessions. Logout/expiry clears this cache. A fresh connection
  without cached sessions must reconnect to load them; it does not delete them.
- Both direct generation and chat memory detect language from the original
  current query with a seeded local langdetect factory and rules for short
  English/Spanish questions and Roman Urdu. History, retrieval rewrites and
  sources do not select response language. Ambiguous standalone medical terms
  default to English. A clear script/statistical mismatch triggers one bounded
  regeneration; a persistent mismatch raises a 502 and does not commit the turn.
  This is a practical guard, not perfect language identification for every mixed
  or ambiguous input. Normal successful requests make no extra model call.
- The sidebar lists all 36 configured topics from `medrag.topics.TOPICS`, also
  imported by ingestion. It names PubMed, OpenFDA drug labels and WHO guidelines,
  explains coverage differences and acknowledges session-scoped uploaded PDFs.
  It does not claim every condition has evidence from all three sources.
- Browser verification with two unnamed chats reproduced the disappearing
  question, then confirmed the fix, a Diabetes Type 2 label and saved history
  after refresh (`audit/phase21_chat_refresh.png`). The topic panel was opened and
  verified with all 36 names (`audit/phase21_topics_panel.png`). Tests cover forced
  sidebar reruns, distinct duplicate labels and interrupted session reads.
- Live model checks against a small supplied test context returned English for
  the exact English follow-up, Spanish for a Spanish question and Urdu for an
  Urdu question, despite a previous Russian response. English/Spanish retained
  the citation marker; Urdu omitted it in that sample. General citation adherence
  remains a model-quality limit; this change validates language, not every claim.
  See [langdetect](https://pypi.org/project/langdetect/) for the detector's documented
  ambiguity and reproducibility settings. The dependency is pinned at 1.0.9.

## Isolation remains enforced

Missing retrieval identity means curated-only. An explicit session scope adds
only that session's published uploads. Full corpus access requires the internal
keyword `full_corpus_evaluation=True`; it cannot be combined with an identity
and is not exposed by `/chat`. See `retrieval_isolation.md` for affected internal
evaluation scripts and notebook call sites. These UI changes do not widen scope.

Restart the backend and Streamlit processes to load these changes. Sign in once
after upgrading to establish the new browser cookie. CI/CD and hosting remain
the next phases; this follow-up does not implement or deploy them.
