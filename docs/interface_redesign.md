# MedRAG interface redesign

Implemented the approved midnight-blue design in Streamlit. Public navigation has
Overview (the default), Log in, and Create account. The signed-in navbar contains
only Sign out. The workspace provides research chat, saved conversations,
supporting references directly below each answer, and Topics & sources with all
36 topics as wrapping tags. There is no separate evidence sidebar.
Backend health and the duplicate topic-list expander are omitted from the sidebar.
The source directory uses compact 17-pixel resource titles and 13-pixel
descriptions with tight dividers. During generation, the question and loading
response remain above the disabled composer, matching the completed-answer
layout; PDF indexing feedback also appears above the composer.

The chat composer's native **+** control accepts PDFs up to the existing 20 MB
backend limit. A submitted PDF is indexed in the active conversation before the
accompanying question is sent. A failed upload leaves the question unsent and
visible for recovery. File-only submissions are supported, and first-time users
can start a conversation by sending a question without creating one manually.

Authentication feedback uses a centered, dismissible dialog. Failed login keeps
the existing account form available for retry; successful login confirms that
the workspace is ready. The submit button is disabled while authentication is
in progress. A stable, hidden authentication-component slot prevents page
elements from shifting and temporarily showing a second copy of the form.

## Refresh and authentication

- The existing HttpOnly session cookie restores authentication after a browser
  refresh. Tokens are never placed in URLs or local storage.
- `page`, `view`, and `chat` query parameters retain the page, workspace section,
  and selected conversation. A conversation is loaded only after it is found in
  the signed-in user's session list; the API still enforces ownership.
- Successful login/registration passes the API token through the existing
  origin-checked component channel into Streamlit's private session state. This
  updates the current connection without attempting blocked iframe navigation.
  Later page loads use the persistent cookie.
- Sign out revokes the session through the existing API, clears private page
  state, and ignores the old connection's cookie snapshot. Expired or revoked
  sessions return to login.
- Unsent drafts and locally selected files are temporary; refresh restores saved
  conversations and indexed documents, rather than resubmitting work.

## Responsive behavior

Public hero/features and account forms stack on small screens. Workspace sources
stay beneath their respective answers at every width, the sidebar uses Streamlit's mobile
drawer, and topic tags wrap. Buttons have at least 44-pixel heights. The shared
theme configuration is included in local, Docker, and Modal packaging.

## Verification

Run from the repository root with `PYTHONPATH=backend/src;backend` on Windows
(use `:` as the separator on Unix):

```text
python -m pytest tests/unit/test_frontend.py tests/unit/test_interface_navigation.py tests/unit/test_modal_startup.py -q
node --test tests/frontend/auth_bridge.test.cjs
python tests/frontend/check_interface.py
```

Verified locally:

- 18 Python interface/navigation/startup tests passed, including authentication
  restoration, expired sessions, unowned conversation URLs, source figures and
  tables, failed password confirmation, and first-question session creation.
- 5 JavaScript authentication-bridge tests passed.
- 37 browser checks passed in installed Chrome against a synthetic local API.
  Landing, login, sign-up, workspace, and topics were checked at widths 320, 375,
  768, 1024, and 1440 pixels, including horizontal-overflow checks. Workflow
  checks covered both account entry points, HttpOnly cookie restoration,
  conversation/section refresh, PDF-before-question ordering, no upload replay
  on refresh, sign-out followed by refresh, successful-login confirmation, and
  failed-login retry with one account page and centered dialogs at desktop and
  mobile widths, the composer below the loading turn, and sources within their
  corresponding answer. Screenshots and results are
  generated in ignored `ci-reports/interface/`.

The browser fixture does not use real accounts, databases, PDF extraction, or
medical generation. This verifies UI behavior, not live backend availability or
medical output. Physical devices and browsers other than Chrome were not tested.
The broader backend suite could not run in this interface-only environment:
additional attempted tests required missing backend packages (`qdrant_client`,
`pydantic_settings`, and `fastapi`). No live deployment was performed.
