# LabGuide Frontend MVP Tasks

## Goal

Build a `Textual`-based TUI that captures a screenshot, sends it to the local backend, and displays the response with stable status handling.

## Milestone 1: App Shell

### Task 1.1: Create base application layout
- Build the main `Textual` app shell
- Add transcript panel, prompt input, metadata panel, and status bar
- Add keyboard bindings for send, clear, and quit

**Acceptance criteria**
- App launches without crashing
- User can see where to type, where responses appear, and current status
- Keyboard bindings are visible and functional

### Task 1.2: Add transcript rendering helpers
- Render user messages, assistant messages, and errors distinctly
- Add session clear behavior
- Keep transcript state in memory for the current session

**Acceptance criteria**
- Messages append in order
- Clear resets both transcript and in-memory history
- Error messages are visually distinct

## Milestone 2: Config and Startup

### Task 2.1: Add local config loading
- Load config from `labguide.toml`
- Fall back to sensible defaults if optional fields are omitted
- Surface config errors in a readable way

**Acceptance criteria**
- App can start with a local config file
- Missing optional fields do not crash the app
- Invalid config produces a readable startup error

### Task 2.2: Add backend metadata display
- Show backend base URL, configured model, and OpenAI API paths in the side panel
- Track last latency and request outcome

**Acceptance criteria**
- Side panel updates after each request
- Operator can confirm which backend the app is pointed at

## Milestone 3: Screenshot and Request Flow

### Task 3.1: Add screenshot capture helper
- Capture the primary display with `mss`
- Encode as JPEG with configurable quality
- Collect minimal screen metadata

**Acceptance criteria**
- A screenshot can be captured on demand
- Helper returns base64 image data plus metadata
- Capture failures propagate as readable errors

### Task 3.2: Implement request payload construction
- Build an OpenAI-compatible `/v1/chat/completions` payload from message, screenshot, metadata, and recent history
- Limit included history to configured turn count

**Acceptance criteria**
- Payload matches the OpenAI-compatible backend contract
- Most recent turns are included consistently
- Optional fields are omitted cleanly when unavailable

### Task 3.3: Implement backend client
- Send synchronous logical requests over `httpx`
- Authenticate with `Authorization: Bearer ...` when configured
- Parse success and error responses
- Return latency and model metadata when present

**Acceptance criteria**
- Backend success response renders in transcript
- Timeout and network failures become readable TUI errors
- No request leaves the UI stuck in a loading state

## Milestone 4: UX Hardening

### Task 4.1: Add request lifecycle states
- Update status as the app moves through capture, encode, send, and response
- Check `/v1/models` on startup to confirm backend reachability
- Prevent double-submission while a request is in flight

**Acceptance criteria**
- Status transitions are visible
- User cannot accidentally start multiple overlapping submissions

### Task 4.2: Add minimal local session logging
- Write JSONL entries for request/response metadata
- Keep raw screenshots out of logs by default

**Acceptance criteria**
- Each request produces one structured log entry
- Log file can be disabled by config

## Milestone 5: Verification

### Task 5.1: Manual smoke test script
- Test with a running backend
- Exercise at least five known scenarios from the PRD

**Suggested scenarios**
- Printer offline dialog
- Browser access error
- Login prompt confusion
- File save dialog issue
- App launch failure dialog

### Task 5.2: Lightweight code verification
- Run syntax compilation on the frontend package
- Validate request schema examples against the backend doc

**Acceptance criteria**
- Frontend source compiles cleanly
- Backend spec and payload builder remain aligned

## Suggested Build Order

1. App shell
2. Config loading
3. Screenshot capture
4. Backend client
5. Request lifecycle and logging
6. Manual verification
