# ACP Demo Python Client

This is a small headless Python ACP client. It launches an ACP agent process
over stdio, initializes the ACP connection, creates/reuses a session, sends a
prompt, and collects `session/update` events.

See [ARCHITECTURE.md](ARCHITECTURE.md) for the project architecture diagrams
and [WEB_SERVER_ARCHITECTURE.md](WEB_SERVER_ARCHITECTURE.md) for the browser UI
runtime design.

## Setup

```bash
cd /Users/simontan/dev/acp_demo
python3 -m venv .venv
source .venv/bin/activate
python -m pip install -r requirements.txt
```

## Run Against Hermes ACP

Hermes is the easiest local smoke test if `hermes` is on your `PATH`:

```bash
python main.py --agent hermes "hello"
```

Equivalent custom command:

```bash
python main.py --agent custom --command hermes --arg acp "hello"
```

## Run Against Codex / Claude Code ACP Adapters

These require Node.js and the adapter packages:

```bash
python main.py --agent codex "Summarize this repository in five bullets"
python main.py --agent claude "Review the current project structure"
```

By default the demo launches:

```text
npx -y @agentclientprotocol/codex-acp
npx -y @agentclientprotocol/claude-agent-acp
```

For Codex, the demo also passes `CODEX_PATH` to the adapter when it can find
`codex` on your `PATH`. This makes `codex-acp` use the same Codex CLI that
already works in your terminal:

```bash
which codex
codex --version
python main.py --agent codex --cwd /path/to/repo "hello"
```

If needed, override it explicitly:

```bash
python main.py --agent codex \
  --codex-path /usr/local/bin/codex \
  --cwd /path/to/repo \
  "Summarize this repository"
```

For lower startup latency, install adapter packages and pass their bin directly:

```bash
npm view @agentclientprotocol/codex-acp bin
npm view @agentclientprotocol/claude-agent-acp bin

python main.py --agent custom --command <codex-acp-bin> "fix the tests"
```

## Interactive Mode

Interactive mode keeps one ACP adapter process and one ACP session alive:

```bash
python main.py --agent hermes --interactive
python main.py --agent codex --interactive --cwd /path/to/repo
```

Use `/exit` or `/quit` to stop.

## Web Chat UI

Run the local browser UI:

```bash
python web_server.py --host 127.0.0.1 --port 8765
```

Then open:

```text
http://127.0.0.1:8765
```

The page lets you select an agent, set the workspace `cwd`, configure a custom
ACP command, choose a permission policy, and chat with the selected agent. The
server keeps ACP runners alive per browser session and agent settings, so
multiple turns can reuse the same adapter process. Press Enter to send and
Shift+Enter to insert a newline.

## JSON Output

```bash
python main.py --agent hermes --format json "hello"
```

The JSON includes:

- `final_text`
- `thought_text`
- `tool_events`
- `plan_events`
- `usage_events`
- `stderr_tail`

When an ACP request fails, the client prints the JSON-RPC error code/data and
the adapter stderr tail. For Codex failures during session creation, first
check that the same Codex CLI works directly:

```bash
codex --version
codex
python main.py --agent codex --codex-path "$(which codex)" "hello"
```

## Raw ACP Trace

Use `--trace-acp` to print every ACP JSON-RPC message to stderr:

```bash
python main.py --agent codex --trace-acp "hello"
```

The trace includes outgoing requests, incoming responses, and incoming
notifications, for example:

```text
[acp    12ms outgoing request initialize id=0]
{"jsonrpc":"2.0","id":0,"method":"initialize","params":{...}}
[acp   230ms incoming response id=0]
{"jsonrpc":"2.0","id":0,"result":{...}}
```

## Permission Policy

Default permission policy is `deny`:

```bash
python main.py --agent codex --permission deny "read the repo"
```

Other options:

```bash
python main.py --agent codex --permission ask "run tests"
python main.py --agent codex --permission allow "run tests"
```

Use `allow` only in a sandboxed workspace you trust.
