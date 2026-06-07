#!/usr/bin/env python3
"""Small local web UI for chatting with ACP agents."""

from __future__ import annotations

import argparse
import asyncio
import json
import secrets
import threading
import time
from dataclasses import dataclass
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from urllib.parse import urlparse

from main import AGENT_REGISTRY, AcpAgentRunner, build_adapter_env, resolve_command


DEFAULT_PORT = 8765
SESSION_COOKIE = "acp_demo_session"


HTML = r"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>ACP Agent Chat</title>
  <style>
    :root {
      color-scheme: light;
      --bg: #f6f7f9;
      --panel: #ffffff;
      --panel-2: #f0f3f7;
      --line: #d9dee7;
      --text: #18202b;
      --muted: #637083;
      --accent: #1f7a5c;
      --accent-2: #0f5f47;
      --danger: #b42318;
      --shadow: 0 10px 30px rgba(24, 32, 43, 0.08);
      font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
    }

    * { box-sizing: border-box; }
    body {
      margin: 0;
      background: var(--bg);
      color: var(--text);
      min-height: 100vh;
    }

    .app {
      display: grid;
      grid-template-columns: 320px minmax(0, 1fr);
      min-height: 100vh;
    }

    aside {
      background: var(--panel);
      border-right: 1px solid var(--line);
      padding: 18px;
      overflow: auto;
    }

    main {
      display: grid;
      grid-template-rows: auto minmax(0, 1fr) auto;
      min-width: 0;
      min-height: 100vh;
    }

    .brand {
      font-size: 18px;
      font-weight: 700;
      margin: 0 0 18px;
    }

    .field {
      display: grid;
      gap: 6px;
      margin-bottom: 14px;
    }

    label {
      font-size: 12px;
      color: var(--muted);
      font-weight: 650;
      text-transform: uppercase;
      letter-spacing: 0;
    }

    input, select, textarea, button {
      font: inherit;
    }

    input, select, textarea {
      width: 100%;
      border: 1px solid var(--line);
      border-radius: 6px;
      background: #fff;
      color: var(--text);
      padding: 9px 10px;
      outline: none;
    }

    textarea {
      min-height: 44px;
      max-height: 180px;
      resize: vertical;
      line-height: 1.45;
    }

    input:focus, select:focus, textarea:focus {
      border-color: var(--accent);
      box-shadow: 0 0 0 3px rgba(31, 122, 92, 0.12);
    }

    .row {
      display: grid;
      grid-template-columns: 1fr 1fr;
      gap: 10px;
    }

    .hint {
      color: var(--muted);
      font-size: 12px;
      line-height: 1.4;
      margin: 4px 0 0;
    }

    .custom-fields[hidden] {
      display: none;
    }

    .actions {
      display: flex;
      gap: 8px;
      margin-top: 18px;
    }

    button {
      border: 1px solid transparent;
      border-radius: 6px;
      padding: 9px 12px;
      cursor: pointer;
      font-weight: 650;
      white-space: nowrap;
    }

    .primary {
      background: var(--accent);
      color: #fff;
    }

    .primary:hover { background: var(--accent-2); }

    .secondary {
      background: #fff;
      border-color: var(--line);
      color: var(--text);
    }

    .secondary:hover { background: var(--panel-2); }

    button:disabled {
      opacity: 0.55;
      cursor: not-allowed;
    }

    header {
      display: flex;
      align-items: center;
      justify-content: space-between;
      gap: 12px;
      padding: 16px 22px;
      border-bottom: 1px solid var(--line);
      background: rgba(255, 255, 255, 0.88);
      backdrop-filter: blur(10px);
    }

    .title {
      min-width: 0;
    }

    .title h1 {
      font-size: 18px;
      margin: 0;
    }

    .title p {
      margin: 4px 0 0;
      color: var(--muted);
      font-size: 13px;
      overflow: hidden;
      text-overflow: ellipsis;
      white-space: nowrap;
    }

    .status {
      color: var(--muted);
      font-size: 13px;
      white-space: nowrap;
    }

    .messages {
      padding: 22px;
      overflow: auto;
      display: flex;
      flex-direction: column;
      gap: 14px;
    }

    .message {
      max-width: min(860px, 86%);
      border: 1px solid var(--line);
      border-radius: 8px;
      padding: 12px 14px;
      background: var(--panel);
      box-shadow: var(--shadow);
    }

    .message.user {
      align-self: flex-end;
      background: #eaf4ef;
      border-color: #bdd8ce;
      box-shadow: none;
    }

    .message.error {
      border-color: #f0b8b4;
      background: #fff4f2;
    }

    .meta {
      display: flex;
      justify-content: space-between;
      gap: 12px;
      color: var(--muted);
      font-size: 12px;
      margin-bottom: 6px;
    }

    .body {
      white-space: pre-wrap;
      line-height: 1.5;
      overflow-wrap: anywhere;
    }

    details {
      margin-top: 10px;
    }

    summary {
      color: var(--muted);
      cursor: pointer;
      font-size: 12px;
    }

    pre {
      overflow: auto;
      background: #101820;
      color: #e6edf3;
      border-radius: 6px;
      padding: 10px;
      font-size: 12px;
      line-height: 1.45;
    }

    .composer {
      border-top: 1px solid var(--line);
      padding: 14px 22px 18px;
      background: var(--panel);
      display: grid;
      grid-template-columns: minmax(0, 1fr) auto;
      gap: 10px;
      align-items: end;
    }

    .composer textarea {
      min-height: 52px;
    }

    @media (max-width: 820px) {
      .app {
        grid-template-columns: 1fr;
      }
      aside {
        border-right: 0;
        border-bottom: 1px solid var(--line);
      }
      main {
        min-height: 70vh;
      }
      .message {
        max-width: 100%;
      }
      .composer {
        grid-template-columns: 1fr;
      }
    }
  </style>
</head>
<body>
  <div class="app">
    <aside>
      <p class="brand">ACP Agent Chat</p>
      <form id="settings">
        <div class="field">
          <label for="agent">Agent</label>
          <select id="agent" name="agent">
            <option value="codex">Codex</option>
            <option value="claude">Claude Code</option>
            <option value="hermes">Hermes</option>
            <option value="copilot">Copilot</option>
            <option value="custom">Custom</option>
          </select>
        </div>

        <div class="field">
          <label for="cwd">Workspace</label>
          <input id="cwd" name="cwd" autocomplete="off">
          <p class="hint">Sent to ACP as session/new cwd.</p>
        </div>

        <div class="custom-fields" id="customFields" hidden>
          <div class="field">
            <label for="command">Command</label>
            <input id="command" name="command" placeholder="codex-acp">
          </div>
          <div class="field">
            <label for="args">Arguments</label>
            <input id="args" name="args" placeholder="--stdio">
            <p class="hint">Split with shell-style quoting.</p>
          </div>
        </div>

        <div class="field">
          <label for="codexPath">Codex Path</label>
          <input id="codexPath" name="codexPath" placeholder="/usr/local/bin/codex">
        </div>

        <div class="row">
          <div class="field">
            <label for="permission">Permission</label>
            <select id="permission" name="permission">
              <option value="deny">Deny</option>
              <option value="allow">Allow</option>
            </select>
          </div>
          <div class="field">
            <label for="timeout">Timeout</label>
            <input id="timeout" name="timeout" type="number" min="5" step="1" value="900">
          </div>
        </div>

        <div class="actions">
          <button class="secondary" id="resetBtn" type="button">Reset Session</button>
          <button class="secondary" id="clearBtn" type="button">Clear Chat</button>
        </div>
      </form>
    </aside>

    <main>
      <header>
        <div class="title">
          <h1 id="chatTitle">Codex</h1>
          <p id="chatSubtitle"></p>
        </div>
        <div class="status" id="status">Ready</div>
      </header>

      <section class="messages" id="messages"></section>

      <form class="composer" id="composer">
        <textarea id="prompt" placeholder="Ask the selected agent..." required></textarea>
        <button class="primary" id="sendBtn" type="submit">Send</button>
      </form>
    </main>
  </div>

  <script>
    const els = {
      agent: document.querySelector("#agent"),
      cwd: document.querySelector("#cwd"),
      command: document.querySelector("#command"),
      args: document.querySelector("#args"),
      codexPath: document.querySelector("#codexPath"),
      permission: document.querySelector("#permission"),
      timeout: document.querySelector("#timeout"),
      customFields: document.querySelector("#customFields"),
      messages: document.querySelector("#messages"),
      composer: document.querySelector("#composer"),
      prompt: document.querySelector("#prompt"),
      sendBtn: document.querySelector("#sendBtn"),
      resetBtn: document.querySelector("#resetBtn"),
      clearBtn: document.querySelector("#clearBtn"),
      status: document.querySelector("#status"),
      chatTitle: document.querySelector("#chatTitle"),
      chatSubtitle: document.querySelector("#chatSubtitle"),
    };

    const labels = {
      codex: "Codex",
      claude: "Claude Code",
      hermes: "Hermes",
      copilot: "Copilot",
      custom: "Custom Agent",
    };

    function payload() {
      return {
        agent: els.agent.value,
        cwd: els.cwd.value.trim(),
        command: els.command.value.trim(),
        args: els.args.value.trim(),
        codex_path: els.codexPath.value.trim(),
        permission: els.permission.value,
        timeout: Number(els.timeout.value || 900),
      };
    }

    function setBusy(isBusy) {
      els.sendBtn.disabled = isBusy;
      els.resetBtn.disabled = isBusy;
      els.status.textContent = isBusy ? "Running" : "Ready";
    }

    function updateAgentUi() {
      const name = labels[els.agent.value] || els.agent.value;
      els.customFields.hidden = els.agent.value !== "custom";
      els.chatTitle.textContent = name;
      els.chatSubtitle.textContent = els.cwd.value.trim() || "Current server directory";
    }

    function addMessage(role, text, details) {
      const node = document.createElement("article");
      node.className = `message ${role}`;
      const meta = document.createElement("div");
      meta.className = "meta";
      meta.innerHTML = `<span>${role === "user" ? "You" : role === "error" ? "Error" : labels[els.agent.value] || "Agent"}</span><span>${new Date().toLocaleTimeString()}</span>`;
      const body = document.createElement("div");
      body.className = "body";
      body.textContent = text || "(no agent message received)";
      node.append(meta, body);
      if (details) {
        const d = document.createElement("details");
        const s = document.createElement("summary");
        s.textContent = "Details";
        const pre = document.createElement("pre");
        pre.textContent = JSON.stringify(details, null, 2);
        d.append(s, pre);
        node.append(d);
      }
      els.messages.append(node);
      els.messages.scrollTop = els.messages.scrollHeight;
    }

    async function postJson(url, body) {
      const res = await fetch(url, {
        method: "POST",
        headers: {"Content-Type": "application/json"},
        body: JSON.stringify(body),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        const msg = data.message || data.error || `HTTP ${res.status}`;
        throw Object.assign(new Error(msg), {data});
      }
      return data;
    }

    els.agent.addEventListener("change", updateAgentUi);
    els.cwd.addEventListener("input", updateAgentUi);
    els.clearBtn.addEventListener("click", () => {
      els.messages.replaceChildren();
    });
    els.resetBtn.addEventListener("click", async () => {
      setBusy(true);
      try {
        await postJson("/api/reset", payload());
        els.messages.replaceChildren();
        els.status.textContent = "Session reset";
      } catch (err) {
        addMessage("error", err.message, err.data);
      } finally {
        setBusy(false);
      }
    });

    els.composer.addEventListener("submit", async (event) => {
      event.preventDefault();
      const prompt = els.prompt.value.trim();
      if (!prompt) return;
      addMessage("user", prompt);
      els.prompt.value = "";
      setBusy(true);
      try {
        const result = await postJson("/api/chat", {...payload(), prompt});
        addMessage("agent", result.final_text, result);
      } catch (err) {
        addMessage("error", err.message, err.data);
      } finally {
        setBusy(false);
        els.prompt.focus();
      }
    });

    els.prompt.addEventListener("keydown", (event) => {
      if (event.key === "Enter" && !event.shiftKey) {
        els.composer.requestSubmit();
        event.preventDefault();
      }
    });

    async function init() {
      const res = await fetch("/api/config");
      const config = await res.json();
      els.cwd.value = config.cwd;
      els.codexPath.value = config.codex_path || "";
      updateAgentUi();
      addMessage("agent", "Select an agent and send a prompt.");
    }

    init().catch((err) => addMessage("error", err.message));
  </script>
</body>
</html>
"""


@dataclass(frozen=True)
class RunnerKey:
    browser_session: str
    agent: str
    command: str
    args: tuple[str, ...]
    cwd: str
    permission: str
    codex_path: str


class AsyncRuntime:
    def __init__(self) -> None:
        self.loop = asyncio.new_event_loop()
        self.thread = threading.Thread(
            target=self._run, name="acp-web-loop", daemon=True
        )
        self.thread.start()

    def _run(self) -> None:
        asyncio.set_event_loop(self.loop)
        self.loop.run_forever()

    def run(self, coro: Any, timeout: float | None = None) -> Any:
        future = asyncio.run_coroutine_threadsafe(coro, self.loop)
        return future.result(timeout=timeout)

    def stop(self) -> None:
        self.loop.call_soon_threadsafe(self.loop.stop)
        self.thread.join(timeout=5)


class RunnerManager:
    def __init__(self, runtime: AsyncRuntime) -> None:
        self.runtime = runtime
        self.runners: dict[RunnerKey, AcpAgentRunner] = {}
        self.lock = threading.Lock()

    def prompt(self, browser_session: str, request: dict[str, Any]) -> dict[str, Any]:
        return self.runtime.run(
            self._prompt(browser_session, request),
            timeout=float(request["timeout"]) + 30,
        )

    def reset(self, browser_session: str, request: dict[str, Any]) -> None:
        self.runtime.run(self._reset(browser_session, request), timeout=30)

    def close_all(self) -> None:
        self.runtime.run(self._close_all(), timeout=30)

    async def _prompt(
        self, browser_session: str, request: dict[str, Any]
    ) -> dict[str, Any]:
        key, command, args, env, cwd = self._build_runner_parts(
            browser_session, request
        )
        runner = await self._get_runner(key, command, args, env, cwd, request)
        return await runner.prompt(
            request["prompt"], cwd=cwd, timeout=float(request["timeout"])
        )

    async def _reset(self, browser_session: str, request: dict[str, Any]) -> None:
        target_prefix = (browser_session, request["agent"])
        with self.lock:
            keys = [
                key
                for key in self.runners
                if (key.browser_session, key.agent) == target_prefix
            ]
            runners = [self.runners.pop(key) for key in keys]
        for runner in runners:
            await runner.close()

    async def _close_all(self) -> None:
        with self.lock:
            runners = list(self.runners.values())
            self.runners.clear()
        for runner in runners:
            await runner.close()

    async def _get_runner(
        self,
        key: RunnerKey,
        command: str,
        args: list[str],
        env: dict[str, str],
        cwd: Path,
        request: dict[str, Any],
    ) -> AcpAgentRunner:
        with self.lock:
            runner = self.runners.get(key)
        if runner is not None:
            return runner

        runner = AcpAgentRunner(
            name=request["agent"],
            command=command,
            args=args,
            cwd=cwd,
            env=env,
            permission_policy=request["permission"],
            verbose=False,
            trace_acp=False,
        )
        await runner.start()
        with self.lock:
            existing = self.runners.get(key)
            if existing is not None:
                await runner.close()
                return existing
            self.runners[key] = runner
        return runner

    def _build_runner_parts(
        self, browser_session: str, request: dict[str, Any]
    ) -> tuple[RunnerKey, str, list[str], dict[str, str], Path]:
        namespace = SimpleNamespace(
            agent=request["agent"],
            command=request.get("command") or None,
            arg=request.get("arg") or [],
            env=[],
            codex_path=request.get("codex_path") or None,
        )
        command, args = resolve_command(namespace)
        env = build_adapter_env(namespace)
        cwd = Path(request["cwd"]).expanduser().resolve()
        key = RunnerKey(
            browser_session=browser_session,
            agent=request["agent"],
            command=command,
            args=tuple(args),
            cwd=str(cwd),
            permission=request["permission"],
            codex_path=request.get("codex_path") or "",
        )
        return key, command, args, env, cwd


class AcpWebServer(ThreadingHTTPServer):
    def __init__(self, server_address: tuple[str, int], manager: RunnerManager):
        super().__init__(server_address, AcpRequestHandler)
        self.manager = manager


class AcpRequestHandler(BaseHTTPRequestHandler):
    server: AcpWebServer

    def log_message(self, fmt: str, *args: Any) -> None:
        print(f"{self.address_string()} - {fmt % args}")

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/":
            self._send_html(HTML)
            return
        if path == "/api/config":
            self._send_json(
                {
                    "agents": sorted(AGENT_REGISTRY),
                    "cwd": str(Path.cwd()),
                    "codex_path": self._which_codex(),
                }
            )
            return
        self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        session_id = self._browser_session()
        try:
            payload = self._read_json()
            request = self._normalize_request(payload)
            if path == "/api/chat":
                if not request["prompt"]:
                    raise ValueError("prompt is required")
                result = self.server.manager.prompt(session_id, request)
                self._send_json(result)
                return
            if path == "/api/reset":
                self.server.manager.reset(session_id, request)
                self._send_json({"ok": True})
                return
            self.send_error(HTTPStatus.NOT_FOUND)
        except Exception as exc:
            error = {
                "error": type(exc).__name__,
                "message": str(exc),
            }
            code = getattr(exc, "code", None)
            data = getattr(exc, "data", None)
            if code is not None:
                error["code"] = code
            if data is not None:
                error["data"] = data
            self._send_json(error, status=HTTPStatus.BAD_REQUEST)

    def _browser_session(self) -> str:
        cookie = SimpleCookie(self.headers.get("Cookie"))
        morsel = cookie.get(SESSION_COOKIE)
        if morsel and morsel.value:
            return morsel.value
        return secrets.token_urlsafe(18)

    def _read_json(self) -> dict[str, Any]:
        length = int(self.headers.get("Content-Length", "0"))
        raw = self.rfile.read(length)
        if not raw:
            return {}
        data = json.loads(raw.decode("utf-8"))
        if not isinstance(data, dict):
            raise ValueError("Request body must be a JSON object")
        return data

    def _normalize_request(self, payload: dict[str, Any]) -> dict[str, Any]:
        agent = str(payload.get("agent") or "codex")
        if agent not in {*AGENT_REGISTRY, "custom"}:
            raise ValueError(f"Unsupported agent: {agent}")
        prompt = str(payload.get("prompt") or "").strip()
        cwd = str(payload.get("cwd") or Path.cwd()).strip()
        command = str(payload.get("command") or "").strip()
        if agent == "custom" and not command:
            raise ValueError("command is required for custom agent")
        permission = str(payload.get("permission") or "deny")
        if permission not in {"deny", "allow"}:
            raise ValueError("Web UI supports permission deny or allow")
        timeout = float(payload.get("timeout") or 900)
        if timeout < 5:
            raise ValueError("timeout must be at least 5 seconds")
        args = self._split_args(str(payload.get("args") or ""))
        return {
            "agent": agent,
            "prompt": prompt,
            "cwd": cwd,
            "command": command,
            "arg": args,
            "codex_path": str(payload.get("codex_path") or "").strip(),
            "permission": permission,
            "timeout": timeout,
        }

    @staticmethod
    def _split_args(value: str) -> list[str]:
        if not value.strip():
            return []
        import shlex

        return shlex.split(value)

    @staticmethod
    def _which_codex() -> str:
        import shutil

        return shutil.which("codex") or ""

    def _send_html(self, body: str) -> None:
        data = body.encode("utf-8")
        self.send_response(HTTPStatus.OK)
        self._set_session_cookie()
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _send_json(
        self, body: dict[str, Any], status: HTTPStatus = HTTPStatus.OK
    ) -> None:
        data = json.dumps(body, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self._set_session_cookie()
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _set_session_cookie(self) -> None:
        session_id = self._browser_session()
        self.send_header(
            "Set-Cookie",
            f"{SESSION_COOKIE}={session_id}; Path=/; SameSite=Lax; HttpOnly",
        )


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Run the ACP demo web UI.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    return parser


def main() -> None:
    args = build_parser().parse_args()
    runtime = AsyncRuntime()
    manager = RunnerManager(runtime)
    server = AcpWebServer((args.host, args.port), manager)
    url = f"http://{args.host}:{args.port}"
    print(f"ACP Agent Chat running at {url}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
        manager.close_all()
        runtime.stop()


if __name__ == "__main__":
    main()
