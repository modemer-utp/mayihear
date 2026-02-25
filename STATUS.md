# MayiHear — Project Context & Status

## Problem Statement
Directors and high-rank employees at UTP (utp.edu.pe) are overwhelmed with back-to-back status meetings (8am–12pm daily). They don't have time even for breakfast. They need structured output — summaries, decisions, action items — not the meetings themselves.

Target users: directors and high-rank employees at a university organization (utp.edu.pe domain).

---

## All Options Evaluated

### Option A — ❌ Rejected: Microsoft Teams API Integration
**Viability: LOW for MVP, HIGH long-term**
- Requires Azure AD app registration with admin consent from utp.edu.pe IT
- Organization won't approve until they see a working product first
- Apps like Read.ai face the same enterprise approval barrier
- Months of IT bureaucracy before writing a useful line of code
- **Decision**: revisit this AFTER proving value with a working MVP

---

### Option B — ❌ Rejected: Physical Microphone in Room
**Viability: LOW**
- Place a mic or phone/tablet in the meeting room to capture audio
- Problems: room echo, background noise, multiple overlapping speakers
- Audio quality too poor for accurate transcription
- No way to separate individual speakers cleanly
- **Decision**: rejected — quality too unreliable

---

### Option C — ⚠️ Possible but Deferred: Browser Extension
**Viability: MEDIUM**
- Chrome/Edge extension that captures audio from Teams running in the browser
- No enterprise approval needed
- Captures clean audio from the web app
- Limitation: only works when Teams is used in browser, not the desktop app
- More complex to build and publish (Chrome Web Store review process)
- **Decision**: viable angle but adds complexity, defer to v2

---

### Option D — ⚠️ Possible but Deferred: VB-Cable (Virtual Audio Cable)
**Viability: MEDIUM-HIGH**
- Third-party free tool that creates a virtual audio device
- Routes audio output → virtual input your app can read
- More broadly compatible across languages and frameworks than WASAPI
- Requires user to install extra software (small friction)
- **Decision**: fallback option if native WASAPI proves problematic, defer for now

---

### Option E — ✅ Chosen: System Audio Loopback + Transcription + LLM Summarization
**Viability: HIGH**
- No enterprise permissions needed
- Works on any meeting platform (Teams, Zoom, Google Meet, in-person)
- Clean digital audio — no room noise, no echo
- Uses OS-native loopback APIs — no extra software on Windows and Linux
- Cross-platform viable (Windows native, Linux native, Mac with BlackHole free install)
- Can have a working proof of concept in an afternoon

---

## How It Works (Core Concept)

When a meeting is running on the computer, audio plays through the speakers/headphones.
The OS exposes this audio stream as a virtual "loopback" input — your app captures it as clean digital audio without touching Teams or any platform.

```
Teams / Zoom / any app
        ↓
Windows audio output
        ↓
WASAPI Loopback (virtual capture — no hardware, no noise)
        ↓
Your app receives clean audio stream
        ↓
Whisper transcribes it
        ↓
Claude/GPT summarizes it
        ↓
Structured output for the director
```

---

## Cross-Platform Support

| OS      | Method                          | Extra Setup Required        |
|---------|---------------------------------|-----------------------------|
| Windows | WASAPI loopback (built-in)      | None                        |
| Linux   | PulseAudio/PipeWire monitor     | None                        |
| Mac     | BlackHole virtual audio driver  | One-time free install (~2min)|

**MVP priority order**: Windows first → Mac (with onboarding guide) → Linux (just works).

---

## MVP Architecture

### Tech Stack
- **Language**: Python (fastest to prototype)
- **Audio capture**: `soundcard` library (cross-platform)
- **Transcription**: OpenAI Whisper (local, free) or Whisper API
- **Summarization**: Claude API or OpenAI GPT API
- **Desktop app**: TBD — Electron, Tauri, or PyQt

### Output Format (per meeting)
- 3-bullet summary
- Decisions made
- Action items with owners
- Open questions

---

## Known Edge Cases

- **Director's own voice**: loopback only captures remote speakers. To include the director's voice, need to mix mic input + loopback. Planned for v2.
- **Mac setup**: BlackHole requires a one-time manual setup in Audio MIDI Setup (document in onboarding).
- **Multiple meetings back to back**: need a clear start/stop UX so recordings don't bleed into each other.

---

## MVP Constraints (Decided)
- No user auth, no login
- No database
- Local-first — everything lives on the user's machine
- No video — audio only
- Windows first, then Mac + Linux

---

## Context / Insights Strategy

### The Problem
Different UTP departments need different structured output from the same transcript:
- Academic Director → student retention risks, professor actions
- Admin Manager → budget decisions, pending approvals
- IT Coordinator → tickets, blockers, system issues

### Options Evaluated
| Option | Description | Decision |
|---|---|---|
| Free-text profile | User writes paragraph once, used as LLM system prompt | Base of chosen approach |
| Chat-based setup | LLM asks questions, builds profile for you | v2 feature |
| Template library | Pre-built templates per meeting type | Included in MVP as starters |
| Per-recording tag | Quick field before each recording describing the meeting | Included in MVP |
| **Hybrid (chosen)** | Persistent profile + per-recording tag + starter templates | MVP |

### Chosen Approach: Hybrid
1. **Persistent profile** — text area, saved as local JSON, used as system context on every call
2. **Starter templates** — 4-5 pre-built UTP templates (status meeting, retention review, budget, 1-on-1, academic planning)
3. **Per-recording meeting tag** — quick text field before/after each recording
4. LLM combines profile + tag to produce tailored structured output

---

## Full MVP Feature Plan

### Phase 1 — Core Recording Pipeline (current)
- [ ] Electron app scaffold (Windows first)
- [ ] System audio loopback capture (desktopCapturer API)
- [ ] Start / Stop recording UI
- [ ] Auto-transcribe on stop (OpenAI Whisper API)
- [ ] Display raw transcript

### Phase 2 — Context + Insights
- [ ] Context profile editor (text area, saved as local .json)
- [ ] Starter templates (5 UTP-specific ones)
- [ ] Per-recording meeting tag field
- [ ] LLM structured output via Claude API:
  - 3-bullet summary
  - Key decisions made
  - Action items with owners
  - Open questions

### Phase 3 — Usability
- [ ] Copy output to clipboard
- [ ] Export as .txt or .md file
- [ ] Basic session history (local files, no DB)

### Deferred (Post-MVP)
- [ ] Mac support (BlackHole onboarding)
- [ ] Linux support
- [ ] Chat-based context builder
- [ ] Mic + loopback mixing (capture director's own voice)
- [ ] Teams API integration (after proving value to UTP IT)

---

## Tech Stack (Decided)
- **Desktop framework**: Electron (fastest MVP, large ecosystem)
- **Audio capture**: Electron `desktopCapturer` API (system audio loopback, no extra software on Windows)
- **Backend**: Python FastAPI (LangChain + LangGraph) — runs locally on `localhost:8000`
- **Transcription**: OpenAI Whisper API (`whisper-1`) — called from Python API
- **Insights**: Anthropic Claude (`claude-sonnet-4-6`) via LangChain — called from Python API
- **Local storage**: JSON files in app data directory
- **Future**: migrate to Tauri for production

---

## Architecture
```
Electron App (UI + audio capture)
        │
        │ HTTP → localhost:8000
        ▼
FastAPI Python API (mayihear-api/)
        │
        ├── POST /transcription/transcribe  →  Whisper API
        ├── POST /insights/generate         →  LangGraph + Claude
        └── GET  /health
```

---

## Project Structure
```
project_mayihear/
│
├── main.js              # Electron main process, calls Python API
├── preload.js           # Secure renderer ↔ main bridge
├── renderer/
│   ├── index.html
│   ├── styles.css
│   └── app.js
├── package.json
├── .env.example
│
└── mayihear-api/        # Python FastAPI backend
    ├── api/
    │   ├── main.py                          # FastAPI app factory
    │   └── controllers/
    │       ├── transcription_controller.py
    │       └── insights_controller.py
    ├── domain/
    │   └── models/
    │       ├── input/insights_request.py
    │       └── output/
    │           ├── transcript_result.py
    │           └── insights_result.py
    ├── application/
    │   ├── services/
    │   │   ├── transcription_service.py
    │   │   └── insights_service.py
    │   └── handlers/
    │       ├── transcribe_audio.py
    │       └── generate_insights.py
    ├── agents/
    │   ├── insights_agent.py               # LangGraph single-node graph
    │   ├── states/insights_state.py
    │   ├── utilities/
    │   │   ├── config.py                   # Model selection, temperature
    │   │   ├── model_init.py               # OpenAI / Anthropic init
    │   │   └── helper.py                   # read_prompt_file()
    │   └── prompts/
    │       └── generate_insights.prompt    # <divisor> pattern
    ├── infrastructure/
    │   └── utilities/secret_manager.py
    └── requirements.txt
```

---

## Progress

- [x] Problem scoped and validated
- [x] Teams API integration evaluated and rejected for MVP
- [x] Audio loopback approach confirmed as viable
- [x] Cross-platform strategy defined
- [x] Platform decision: Electron desktop app
- [x] Context/insights strategy decided (hybrid: profile + templates + per-recording tag)
- [x] Full feature plan defined (3 phases)
- [x] Phase 1: Scaffold Electron app
- [x] Separate LLM/agent logic into Python FastAPI (mayihear-api/)
- [x] Python API: Service → Handler → Agent architecture (matches experto-tematico)
- [x] LangGraph InsightsAgent with structured output
- [x] Prompt file with `<divisor>` pattern
- [ ] Phase 1: Test audio capture + transcription end-to-end
- [ ] Phase 2: Context profile + LLM insights wired up in UI
- [ ] Phase 3: Export + session history
- [ ] Validate with real Teams meeting at UTP

---

## Next Steps
1. Scaffold Electron project (package.json, main.js, preload.js, renderer UI)
2. Implement system audio capture with desktopCapturer
3. Wire up Whisper API for transcription
4. Wire up Claude API for insights
5. Test with a real Teams meeting recording
