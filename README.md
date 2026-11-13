# MAMBA — Personal AI Assistant

MAMBA is a personal AI assistant for Windows 11, built primarily in Python using PySide6.

## Repository

Workspace root: `mamba/`

```text
mamba/
├── app.py
├── requirements.txt
├── requirements-dev.txt
├── README.md
├── .env.example
├── core/
├── voice/
├── computer/
├── web/
├── coding/
├── productivity/
├── integrations/
├── system/
├── media/
├── automation/
├── ui/
├── tests/
│   ├── unit/
│   ├── integration/
│   ├── e2e/
│   └── security/
└── data/
```

## Run and configure

Install dependencies with `python -m pip install -r requirements.txt`, then start
the desktop app with `python app.py`. Use the sidebar's INTEGRATIONS page to
choose Gemini, OpenAI, Anthropic, Groq, DeepSeek, OpenRouter, or local Ollama,
then test the connection. Cloud provider keys are stored in Windows Credential
Manager; Ollama needs no key. Provider and model preferences are stored
separately in `data/settings.json`.

### Local AI (Ollama) - works offline

MAMBA can run entirely on a locally installed Ollama model, so AI conversations
work without an internet connection:

1. Install [Ollama](https://ollama.com) and start it (`ollama serve`).
2. Pull the local model: `ollama pull qwen2.5:7b`.
3. In INTEGRATIONS, set **MODE** to one of:
   - **Local (Ollama)** - always uses the local server (`http://localhost:11434`,
     native `/api/chat`, model `qwen2.5:7b`). No API key and no external calls.
   - **Cloud (Groq)** - always uses the configured cloud provider (Groq).
   - **Automatic** - uses the configured cloud provider when online and
     switches to Ollama when offline or when a cloud network request fails.

Local mode never sends prompts to external servers. If Ollama is not running or
the model is missing, MAMBA shows an actionable error (start Ollama / run
`ollama pull qwen2.5:7b`). The mode and the local model can also be set via the
`AI_MODE` and `OLLAMA_MODEL` environment variables in `.env`.

Run `python verify_ollama.py` with the project venv to check the Ollama
connection and confirm Qwen answers a message.

Use the VOICE page for push-to-talk input and spoken replies. Speech input uses
the system microphone and Google's online speech recognition; spoken output
uses the local Windows speech engine. Install PyAudio with the requirements for
microphone access.

The BROWSER page opens URLs and runs live web searches. The SPOTIFY page sends
Windows media keys to the active player and can open Spotify searches; Spotify
must be running for playback controls. The DISCORD page accepts a bot token,
verifies it, and posts to a chosen channel after an explicit confirmation. The
bot needs permission to view and send messages in that channel.

Email can be configured on INTEGRATIONS with your provider's SMTP host, port,
and SSL/STARTTLS setting. Store an app password (not your normal account
password); MAMBA saves it in Windows Credential Manager. Use the panel to test
the connection and review each message before sending. Chat drafts use the form
`email me subject: ... body: ...` and require confirmation.

To make real phone calls, configure `TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`,
and `TWILIO_PHONE_NUMBER` in `.env`, and set `DEFAULT_PHONE_NUMBER` to your
number in international format (for example, `+14155550123`). Install the
requirements and restart MAMBA. Then send `Call me` in chat; Twilio will call
your configured number and play a short MAMBA greeting. Twilio account
permissions, verified caller/recipient numbers, and call charges apply.

## Current Architecture

This is an existing Windows desktop application. `app.py` composes the
services and capability controllers; `ui/main_window.py` contains the PySide6
dashboard. Controllers are loaded independently so a missing optional
dependency can disable one capability without preventing the whole app from
starting.

The AI service in `core/ai_service.py` registers Gemini, Anthropic, OpenAI,
Groq, DeepSeek, OpenRouter, and Ollama. The OpenAI-compatible HTTP provider is
also a reusable implementation, but arbitrary custom endpoints are not yet
exposed as a complete settings workflow. Cloud keys use Windows Credential
Manager through `core/secret_store.py`, with environment variables available
as a development fallback. Ollama uses its native local API and needs no key.

The current modes are **Local**, **Cloud**, and **Automatic**. Local mode never
routes prompts to a cloud provider. Automatic mode uses the configured cloud
provider when internet and credentials are available; otherwise it selects
Ollama when the local server is reachable.
`AIService.chat()` classifies failures, retries selected transient errors, and
can use a configured cloud fallback. In Automatic mode, a cloud network failure
now triggers a bounded Ollama reachability check and uses the local model when
it is available; the original conversation messages are preserved. Invalid
credentials and provider-side errors do not trigger local fallback, and
explicit Cloud mode remains cloud-only. `ConnectivityManager` now informs
request-time provider selection; the separate state-rich `core/ai_router.py`
is not yet integrated with the UI status surface. A local model must already
be installed for offline inference.

Other existing foundations include SQLite-backed memory, task planning and
execution, a guarded tool router, permission/autonomy and emergency-stop
controls, verification helpers, Windows application/window/input/screenshot
controllers, file and terminal tools, browser/search, integrations, and voice
input/output. Code presence is not proof that every device-dependent workflow
or acceptance scenario has been verified.

## Staged Implementation Plan

1. **Baseline and reliability.** Preserve the existing desktop workflows;
  maintain focused unit tests for providers, security, tools, and task
  execution. Async provider HTTP calls now run outside the event loop. The
  dashboard's synchronous orchestration and provider streaming paths still
  need a Qt-safe asynchronous implementation.
2. **Hybrid AI routing.** Connect connectivity state to request-time routing;
  implement bounded online-to-local and recovery transitions, preserve
  conversation messages during fallback, and test offline, timeout,
  authentication, and rate-limit cases separately. Complete streaming and
  user-configurable custom endpoint behavior.
3. **Permissions and execution boundary.** Audit every tool against the
  permission manager; add scoped directory/application authorization,
  command policy, cancellation, and auditable approval decisions. Keep
  critical destructive actions blocked by default.
4. **Desktop and file workflows.** Verify application discovery, accessibility
  controls, mouse/keyboard actions, emergency stop, file previews, bulk
  operation dry-runs, recovery, and independent post-action verification on
  disposable targets.
5. **Development and browser workflows.** Exercise repository inspection,
  guarded edits, terminal execution, tests, browser navigation, and safe
  recovery while preserving pre-existing project changes and requiring
  confirmation for external side effects.
6. **Documents, media, diagnostics, and productivity.** Add only supported
  libraries and clearly label features that require extra software, local
  models, permissions, or paid services. Verify generated outputs and report
  unavailable sensor data instead of estimating it silently.
7. **Persistent autonomous workflows and release acceptance.** Add resumable
  task state and safe retries, then run the offline, online, security,
  responsiveness, and existing-functionality checklists. Publish a capability
  only after its applicable tests pass.

Work proceeds one testable stage at a time. Do not interpret this roadmap as a
claim that every requested capability is already implemented.

## Setup and Verification

Install dependencies and launch the desktop app:

```powershell
python -m pip install -r requirements.txt
python app.py
```

Run the automated suite:

```powershell
python -m pytest -q
```

`python tests/acceptance_test.py` exercises real Windows UI and desktop
automation. It may open applications, move the pointer, capture screenshots,
and create test data; run it only in a suitable interactive test session.

For local inference, install Ollama, start it with `ollama serve`, install a
model with `ollama pull qwen2.5:7b`, then select **Local (Ollama)** in
INTEGRATIONS. Cloud API usage can incur provider charges. Do not put real keys
in source files or commit `.env`.

## Security mindset

Do not implement open-ended destructive capabilities without explicit permission checks.
Do not expose secrets in logs, screenshots, or tool results.
Do not override security policy via memory or external content.

Terminal commands run with the current user's privileges. Setting a working
directory does not sandbox a process or prevent it from accessing other
locations. The current dangerous-command checks are pattern-based safeguards,
not a complete shell parser or security boundary; consequential commands
require confirmation, and critical destructive operations should remain
blocked.

## Acceptance

MVP is not complete until:

- text chat works
- wake word works (`Mamba`, `Hey Mamba`)
- STT + TTS work in English/Russian/Armenian at usable level
- Notepad open → verify → type → screenshot → inspect
- file create → verify → read
- terminal execute → inspect output → detect failure
- web search → live result → sources
- coding workflow: inspect → build → test → diagnose
- autonomy respects SAFE/CONFIRM/RESTRICTED
- emergency stop stops automation
- access revocation cancels further control actions
- verification detects failed actions

## Notes

- Every tool result must be real, not fabricated.
- Every important action must be verified independently.
- Security policy always wins over AI output, webpage content, docs, memory, and downloaded files.
