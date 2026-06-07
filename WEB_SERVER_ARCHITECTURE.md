# Web Server Architecture

`web_server.py` provides a local browser UI for selecting an ACP agent and
chatting with it. It uses only the Python standard library plus the existing
ACP client code from `main.py`.

## System View

```mermaid
flowchart LR
    Browser[Browser UI] -->|GET /| HTTP[AcpRequestHandler]
    Browser -->|GET /api/config| HTTP
    Browser -->|POST /api/chat| HTTP
    Browser -->|POST /api/reset| HTTP

    HTTP --> Manager[RunnerManager]
    Manager --> Runtime[AsyncRuntime]
    Runtime --> Loop[Background asyncio event loop]

    Manager --> Cache[(Runner cache)]
    Cache --> Runner[AcpAgentRunner]
    Runner -->|stdio JSON-RPC| Adapter[ACP adapter process]

    Adapter --> Codex[codex-acp / Codex CLI]
    Adapter --> Claude[claude-agent-acp / Claude Code]
    Adapter --> Hermes[hermes acp / Hermes Agent]
    Adapter --> Custom[Custom ACP command]

    Runner --> MainPy[main.py shared ACP client code]
```

## Request Flow

```mermaid
sequenceDiagram
    participant B as Browser
    participant H as AcpRequestHandler
    participant M as RunnerManager
    participant L as AsyncRuntime loop
    participant R as AcpAgentRunner
    participant A as ACP adapter

    B->>H: POST /api/chat
    H->>H: Read cookie acp_demo_session
    H->>H: Normalize agent/cwd/command/options
    H->>M: prompt(browser_session, request)
    M->>L: run coroutine on background loop
    L->>M: _build_runner_parts()
    M->>M: Build RunnerKey
    alt Runner exists
        M->>R: Reuse cached runner
    else No cached runner
        M->>R: Create AcpAgentRunner
        R->>A: spawn process
        R->>A: initialize
        R->>A: session/new
        M->>M: Store runner in cache
    end
    R->>A: session/prompt
    A-->>R: session/update events
    A-->>R: PromptResponse
    R-->>M: result dict
    M-->>H: result dict
    H-->>B: JSON response
```

## Multi-Turn Reuse

```mermaid
flowchart TD
    ChatRequest[Incoming chat request] --> Cookie[Read browser session cookie]
    Cookie --> Key[Build RunnerKey]
    Key --> Lookup{RunnerKey in cache?}
    Lookup -->|Yes| Reuse[Reuse AcpAgentRunner]
    Lookup -->|No| Create[Start new ACP adapter process]
    Create --> Store[Store runner in cache]
    Store --> Prompt[runner.prompt]
    Reuse --> Prompt
    Prompt --> Session{cwd session exists?}
    Session -->|Yes| Existing[Reuse ACP session_id]
    Session -->|No| NewSession[Send session/new]
    NewSession --> SendPrompt[Send session/prompt]
    Existing --> SendPrompt
    SendPrompt --> Response[Return JSON result]
```

The cache key is:

```python
RunnerKey(
    browser_session,
    agent,
    command,
    args,
    cwd,
    permission,
    codex_path,
)
```

As long as these values stay the same, the web UI reuses:

- the same `AcpAgentRunner`
- the same ACP adapter subprocess
- the same stdio JSON-RPC connection
- the same ACP `session_id` for that `cwd`

## Component Map

```mermaid
classDiagram
    class AcpRequestHandler {
        do_GET()
        do_POST()
        _normalize_request()
        _send_json()
        _browser_session()
    }

    class RunnerManager {
        runners
        prompt()
        reset()
        close_all()
        _get_runner()
        _build_runner_parts()
    }

    class AsyncRuntime {
        loop
        thread
        run(coro, timeout)
        stop()
    }

    class RunnerKey {
        browser_session
        agent
        command
        args
        cwd
        permission
        codex_path
    }

    class AcpAgentRunner {
        start()
        close()
        get_session()
        prompt()
    }

    AcpRequestHandler --> RunnerManager
    RunnerManager --> AsyncRuntime
    RunnerManager --> RunnerKey
    RunnerManager --> AcpAgentRunner
```

## HTTP API

| Endpoint | Method | Purpose |
|---|---|---|
| `/` | `GET` | Returns the single-page HTML/CSS/JS UI. |
| `/api/config` | `GET` | Returns available agents, default cwd, and detected Codex path. |
| `/api/chat` | `POST` | Sends a prompt to the selected ACP agent and returns the result JSON. |
| `/api/reset` | `POST` | Closes cached runners for the current browser session and selected agent. |

## Browser UI Flow

```mermaid
flowchart TD
    PageLoad[Page load] --> Config[GET /api/config]
    Config --> Defaults[Fill cwd and codex path]
    Defaults --> Form[User selects agent/settings]
    Form --> Send{User sends prompt}
    Send -->|Enter| Chat[POST /api/chat]
    Send -->|Click Send| Chat
    Send -->|Shift+Enter| Newline[Insert newline]
    Chat --> Render[Render user and agent messages]
    Render --> Details[Show raw result in Details]
    Form --> Reset[POST /api/reset]
```

## Concurrency Model

`ThreadingHTTPServer` handles HTTP requests in worker threads. ACP operations
must run on an asyncio event loop, so `AsyncRuntime` owns one background loop in
a dedicated daemon thread. The HTTP handler submits coroutines to that loop via
`asyncio.run_coroutine_threadsafe()`.

```mermaid
flowchart LR
    HttpThread[HTTP worker thread] -->|manager.prompt| Runtime[AsyncRuntime.run]
    Runtime -->|run_coroutine_threadsafe| AsyncLoop[Background asyncio loop]
    AsyncLoop --> Runner[AcpAgentRunner async methods]
    Runner --> Adapter[ACP subprocess stdio]
```

## Reset And Shutdown

- `Clear Chat` only clears browser-rendered messages.
- `Reset Session` calls `/api/reset`, closes cached runners for the current
  browser session and selected agent, and forces the next message to start a
  new ACP adapter process/session.
- Stopping `web_server.py` closes all cached runners, shuts down adapter
  subprocesses, and stops the background asyncio loop.
