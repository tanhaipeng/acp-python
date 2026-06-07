# ACP Python Client Architecture

This project is a small headless ACP client. It starts an ACP-compatible agent
process over stdio, sends JSON-RPC requests, collects session updates, and
prints either text or JSON results.

For the browser UI runtime, see
[WEB_SERVER_ARCHITECTURE.md](WEB_SERVER_ARCHITECTURE.md).

## System View

```mermaid
flowchart LR
    User[User / Shell] --> CLI[main.py CLI]
    CLI --> Parser[argparse options]
    Parser --> Registry[Agent registry]
    Registry --> Runner[AcpAgentRunner]

    Runner -->|spawn stdio process| Adapter{ACP agent process}

    Adapter -->|npx -y @agentclientprotocol/codex-acp| CodexACP[codex-acp]
    Adapter -->|npx -y @agentclientprotocol/claude-agent-acp| ClaudeACP[claude-agent-acp]
    Adapter -->|hermes acp| HermesACP[Hermes ACP]
    Adapter -->|custom command| CustomACP[Custom ACP server]

    CodexACP -->|CODEX_PATH / codex app-server| CodexCLI[Codex CLI]
    ClaudeACP --> ClaudeCLI[Claude Code CLI]
    HermesACP --> HermesAgent[Hermes Agent]

    Runner <-->|ACP JSON-RPC over stdio| Adapter
    Runner --> Output[Text / JSON output]
    Runner --> Trace[Optional --trace-acp stderr trace]
```

## Runtime Sequence

```mermaid
sequenceDiagram
    participant U as User
    participant M as main.py
    participant R as AcpAgentRunner
    participant A as ACP Adapter Process
    participant C as HeadlessClient

    U->>M: python main.py --agent codex "prompt"
    M->>M: Parse args and build adapter env
    M->>R: Create runner
    R->>A: Spawn process over stdio
    R->>A: initialize
    A-->>R: InitializeResponse
    R->>A: session/new
    A-->>R: NewSessionResponse(sessionId)
    R->>A: session/prompt
    A-->>C: session/update notifications
    C->>C: Collect message/tool/usage events
    A-->>R: PromptResponse(stopReason, usage)
    R->>M: Build result dict
    M-->>U: Print text or JSON
```

## Code Structure

```mermaid
classDiagram
    class TurnState {
        session_id
        message_chunks
        thought_chunks
        tool_events
        plan_events
        usage_events
        other_events
        final_text
        thought_text
    }

    class AcpTraceLogger {
        enabled
        __call__(event)
    }

    class HeadlessClient {
        permission_policy
        turns
        session_update(session_id, update)
        request_permission(options, session_id, tool_call)
    }

    class AcpAgentRunner {
        command
        args
        cwd
        env
        start()
        close()
        get_session(cwd)
        prompt(text, cwd, timeout)
    }

    TurnState <-- HeadlessClient
    AcpTraceLogger <-- AcpAgentRunner
    HeadlessClient <-- AcpAgentRunner
```

## Main Components

| Component | Responsibility |
|---|---|
| `AGENT_REGISTRY` | Maps friendly agent names to default ACP adapter commands. |
| `build_parser()` | Defines CLI options such as `--agent`, `--cwd`, `--format`, `--trace-acp`, and `--codex-path`. |
| `build_adapter_env()` | Builds the child-process environment and passes `CODEX_PATH` for Codex when available. |
| `AcpAgentRunner` | Owns the ACP process, connection, session cache, prompt calls, timeout cancellation, and stderr tail. |
| `HeadlessClient` | Implements client-side ACP callbacks, especially `session/update` and `request_permission`. |
| `TurnState` | Stores streamed message chunks, thought chunks, tool events, usage, and other events for one turn. |
| `AcpTraceLogger` | Prints every ACP JSON-RPC message observed by the connection when `--trace-acp` is enabled. |
| `emit_result()` | Prints the final response in text or JSON format. |
| `emit_error()` | Prints JSON-RPC errors and adapter stderr tail for debugging. |

## ACP Message Flow

The client uses the `agent-client-protocol` Python package. The package creates
a JSON-RPC connection over newline-delimited stdio frames.

```mermaid
flowchart TD
    A[Client starts adapter process] --> B[initialize]
    B --> C[session/new with cwd]
    C --> D[session/prompt with TextContentBlock]
    D --> E{Adapter events}
    E --> F[session/update agent_message_chunk]
    E --> G[session/update tool_call / tool_call_update]
    E --> H[session/update usage_update]
    E --> I[session/update available_commands_update]
    F --> J[PromptResponse]
    G --> J
    H --> J
    I --> J
    J --> K[Print final result]
```

## Supported Agent Paths

```mermaid
flowchart LR
    CLI[main.py --agent] --> Codex[codex]
    CLI --> Claude[claude]
    CLI --> Hermes[hermes]
    CLI --> Copilot[copilot]
    CLI --> Custom[custom]

    Codex --> CodexAdapter["npx -y @agentclientprotocol/codex-acp"]
    Claude --> ClaudeAdapter["npx -y @agentclientprotocol/claude-agent-acp"]
    Hermes --> HermesAdapter["hermes acp"]
    Copilot --> CopilotAdapter["copilot --acp --stdio"]
    Custom --> CustomCommand["--command plus repeated --arg"]
```

## Notes

- `--cwd` is the workspace path sent to `session/new`; the server uses it as
  the project context for file access, commands, and repository awareness.
- `--trace-acp` prints parsed JSON-RPC messages to stderr. It is not a raw byte
  dump, but it preserves the ACP message bodies.
- `--codex-path` sets `CODEX_PATH` for `codex-acp`, which makes the adapter use
  a known Codex CLI binary.
- Interactive mode keeps one adapter process and reuses the ACP session cache
  per resolved `cwd`.
