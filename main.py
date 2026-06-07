#!/usr/bin/env python3
"""Minimal headless ACP client demo.

Examples:
    python main.py --agent codex "Summarize this repo"
    python main.py --agent claude --cwd /path/to/project "Review changed files"
    python main.py --agent hermes --interactive
    python main.py --agent custom --command hermes --arg acp "hello"

The client speaks Agent Client Protocol over stdio to an ACP agent process.
For Codex and Claude Code, it expects adapter packages that expose ACP:
    - npx -y @agentclientprotocol/codex-acp
    - npx -y @agentclientprotocol/claude-agent-acp
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import shutil
import shlex
import sys
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

AGENT_REGISTRY: dict[str, tuple[str, list[str]]] = {
    "codex": ("npx", ["-y", "@agentclientprotocol/codex-acp"]),
    "claude": ("npx", ["-y", "@agentclientprotocol/claude-agent-acp"]),
    "copilot": ("copilot", ["--acp", "--stdio"]),
    "hermes": ("hermes", ["acp"]),
}


@dataclass
class TurnState:
    """Collected state for one ACP prompt turn."""

    session_id: str
    started_at: float = field(default_factory=time.time)
    message_chunks: list[str] = field(default_factory=list)
    thought_chunks: list[str] = field(default_factory=list)
    tool_events: list[dict[str, Any]] = field(default_factory=list)
    plan_events: list[dict[str, Any]] = field(default_factory=list)
    usage_events: list[dict[str, Any]] = field(default_factory=list)
    other_events: list[dict[str, Any]] = field(default_factory=list)

    @property
    def final_text(self) -> str:
        return "".join(self.message_chunks).strip()

    @property
    def thought_text(self) -> str:
        return "".join(self.thought_chunks).strip()


def _dump_model(value: Any) -> Any:
    """Convert pydantic/dataclass-ish ACP objects to JSON-friendly data."""

    if hasattr(value, "model_dump"):
        return value.model_dump(by_alias=True, mode="json", exclude_none=True)
    if hasattr(value, "dict"):
        return value.dict(by_alias=True, exclude_none=True)
    if isinstance(value, (list, tuple)):
        return [_dump_model(item) for item in value]
    if isinstance(value, dict):
        return {str(k): _dump_model(v) for k, v in value.items()}
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return repr(value)


def _content_text(content: Any) -> str:
    if content is None:
        return ""
    text = getattr(content, "text", None)
    if isinstance(text, str):
        return text
    if isinstance(content, dict):
        value = content.get("text")
        return value if isinstance(value, str) else ""
    return ""


def _json_line(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"))


class AcpTraceLogger:
    """Print every JSON-RPC message crossing the ACP connection."""

    def __init__(self, *, enabled: bool = False):
        self.enabled = enabled
        self._started_at = time.time()

    def __call__(self, event: Any) -> None:
        if not self.enabled:
            return
        elapsed_ms = int((time.time() - self._started_at) * 1000)
        direction = getattr(event, "direction", "")
        direction_value = getattr(direction, "value", str(direction))
        message = getattr(event, "message", {})
        method = message.get("method") if isinstance(message, dict) else None
        message_id = message.get("id") if isinstance(message, dict) else None
        kind = "notification"
        if isinstance(message, dict) and "error" in message:
            kind = "error"
        elif isinstance(message, dict) and "result" in message:
            kind = "response"
        elif message_id is not None and method:
            kind = "request"
        header = f"[acp {elapsed_ms:>6}ms {direction_value} {kind}"
        if method:
            header += f" {method}"
        if message_id is not None:
            header += f" id={message_id}"
        header += "]"
        print(header, file=sys.stderr)
        print(_json_line(message), file=sys.stderr)


class HeadlessClient:
    """ACP client-side callbacks.

    ACP agents call these methods via JSON-RPC notifications/requests while a
    prompt is running. This demo collects updates in memory and optionally
    streams human-readable progress to stderr.
    """

    def __init__(self, *, permission_policy: str = "deny", verbose: bool = False):
        self.permission_policy = permission_policy
        self.verbose = verbose
        self.turns: dict[str, TurnState] = {}

    def reset_turn(self, session_id: str) -> TurnState:
        state = TurnState(session_id=session_id)
        self.turns[session_id] = state
        return state

    def get_turn(self, session_id: str) -> TurnState:
        return self.turns.setdefault(session_id, TurnState(session_id=session_id))

    async def session_update(self, session_id: str, update: Any, **_: Any) -> None:
        state = self.get_turn(session_id)
        data = _dump_model(update)
        update_type = (
            getattr(update, "session_update", None)
            or getattr(update, "sessionUpdate", None)
            or (data.get("sessionUpdate") if isinstance(data, dict) else None)
            or (data.get("session_update") if isinstance(data, dict) else None)
            or ""
        )

        if update_type == "agent_message_chunk":
            text = _content_text(getattr(update, "content", None))
            state.message_chunks.append(text)
            if self.verbose and text:
                print(text, end="", file=sys.stderr, flush=True)
        elif update_type == "agent_thought_chunk":
            text = _content_text(getattr(update, "content", None))
            state.thought_chunks.append(text)
            if self.verbose and text:
                print(f"[thought] {text}", file=sys.stderr)
        elif update_type in {"tool_call", "tool_call_update"}:
            state.tool_events.append(data)
            if self.verbose:
                title = data.get("title") if isinstance(data, dict) else None
                status = data.get("status") if isinstance(data, dict) else None
                print(
                    f"[tool] {title or update_type} {status or ''}".rstrip(),
                    file=sys.stderr,
                )
        elif update_type == "plan":
            state.plan_events.append(data)
        elif update_type == "usage_update":
            state.usage_events.append(data)
        else:
            state.other_events.append(data)

    async def request_permission(
        self,
        options: list[Any],
        session_id: str,
        tool_call: Any,
        **_: Any,
    ) -> Any:
        from acp.schema import AllowedOutcome, DeniedOutcome, RequestPermissionResponse

        if self.permission_policy == "ask":
            print("\nPermission requested:", file=sys.stderr)
            print(
                json.dumps(_dump_model(tool_call), indent=2, ensure_ascii=False),
                file=sys.stderr,
            )
            for idx, option in enumerate(options, start=1):
                name = getattr(option, "name", "")
                kind = getattr(option, "kind", "")
                option_id = getattr(option, "option_id", "")
                print(f"  {idx}. {name} [{kind}] ({option_id})", file=sys.stderr)
            choice = input("Choose option number, blank to deny: ").strip()
            if choice.isdigit():
                i = int(choice) - 1
                if 0 <= i < len(options):
                    opt = options[i]
                    return RequestPermissionResponse(
                        outcome=AllowedOutcome(
                            outcome="selected", optionId=opt.option_id
                        )
                    )

        if self.permission_policy == "allow":
            for option in options:
                if getattr(option, "kind", "") in {"allow_once", "allow_always"}:
                    return RequestPermissionResponse(
                        outcome=AllowedOutcome(
                            outcome="selected", optionId=option.option_id
                        )
                    )

        return RequestPermissionResponse(outcome=DeniedOutcome(outcome="cancelled"))


class AcpAgentRunner:
    """Long-lived connection to one ACP agent process."""

    def __init__(
        self,
        *,
        name: str,
        command: str,
        args: list[str],
        cwd: Path,
        env: dict[str, str] | None,
        permission_policy: str,
        verbose: bool,
        trace_acp: bool,
    ):
        self.name = name
        self.command = command
        self.args = args
        self.cwd = cwd
        self.env = env
        self.trace_logger = AcpTraceLogger(enabled=trace_acp)
        self.client = HeadlessClient(
            permission_policy=permission_policy, verbose=verbose
        )
        self.conn: Any = None
        self.process: Any = None
        self._ctx: Any = None
        self._stderr_task: asyncio.Task | None = None
        self._stderr_tail: list[str] = []
        self._sessions: dict[str, str] = {}
        self._locks: dict[str, asyncio.Lock] = {}

    async def __aenter__(self) -> AcpAgentRunner:
        await self.start()
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        await self.close()

    async def start(self) -> None:
        import acp
        from acp.schema import ClientCapabilities, Implementation

        self._ctx = acp.spawn_agent_process(
            self.client,
            self.command,
            *self.args,
            env=self.env,
            cwd=str(self.cwd),
            observers=[self.trace_logger],
            use_unstable_protocol=True,
        )
        self.conn, self.process = await self._ctx.__aenter__()
        self._stderr_task = asyncio.create_task(self._drain_stderr())
        await self.conn.initialize(
            protocol_version=acp.PROTOCOL_VERSION,
            client_capabilities=ClientCapabilities(),
            client_info=Implementation(
                name="acp-demo-python-client",
                title="ACP Demo Python Client",
                version="0.1.0",
            ),
        )

    async def close(self) -> None:
        if self._ctx is not None:
            await self._ctx.__aexit__(None, None, None)
            self._ctx = None
        if self._stderr_task is not None:
            self._stderr_task.cancel()
            try:
                await self._stderr_task
            except asyncio.CancelledError:
                pass

    async def _drain_stderr(self) -> None:
        if self.process is None or self.process.stderr is None:
            return
        while True:
            line = await self.process.stderr.readline()
            if not line:
                return
            text = line.decode(errors="replace").rstrip()
            self._stderr_tail.append(text)
            self._stderr_tail = self._stderr_tail[-50:]

    async def get_session(self, cwd: Path) -> str:
        key = str(cwd.resolve())
        if key not in self._sessions:
            session = await self.conn.new_session(cwd=key)
            self._sessions[key] = session.session_id
            self._locks[session.session_id] = asyncio.Lock()
        return self._sessions[key]

    async def prompt(self, text: str, *, cwd: Path, timeout: float) -> dict[str, Any]:
        from acp.schema import TextContentBlock

        session_id = await self.get_session(cwd)
        lock = self._locks.setdefault(session_id, asyncio.Lock())
        async with lock:
            self.client.reset_turn(session_id)
            try:
                response = await asyncio.wait_for(
                    self.conn.prompt(
                        session_id=session_id,
                        prompt=[TextContentBlock(type="text", text=text)],
                    ),
                    timeout=timeout,
                )
            except asyncio.TimeoutError:
                try:
                    await self.conn.cancel(session_id=session_id)
                finally:
                    raise

            # Let any final session/update notifications arrive before building
            # the result. Some adapters emit the last text chunk just before or
            # just after PromptResponse.
            await asyncio.sleep(0.2)
            turn = self.client.get_turn(session_id)
            return {
                "agent": self.name,
                "session_id": session_id,
                "stop_reason": getattr(response, "stop_reason", None),
                "final_text": turn.final_text,
                "thought_text": turn.thought_text,
                "tool_events": turn.tool_events,
                "plan_events": turn.plan_events,
                "usage_events": turn.usage_events,
                "other_events": turn.other_events,
                "stderr_tail": list(self._stderr_tail),
            }


def resolve_command(args: argparse.Namespace) -> tuple[str, list[str]]:
    if args.agent == "custom":
        if not args.command:
            raise SystemExit("--command is required with --agent custom")
        return args.command, args.arg or []

    command, default_args = AGENT_REGISTRY[args.agent]
    if args.command:
        command = args.command
        default_args = args.arg or []
    return command, list(default_args)


def parse_env_overrides(values: list[str] | None) -> dict[str, str]:
    env: dict[str, str] = {}
    for item in values or []:
        if "=" not in item:
            raise SystemExit(f"--env must be KEY=VALUE, got: {item}")
        key, value = item.split("=", 1)
        key = key.strip()
        if not key:
            raise SystemExit(f"--env must include a variable name, got: {item}")
        env[key] = value
    return env


def build_adapter_env(args: argparse.Namespace) -> dict[str, str]:
    env = dict(os.environ)
    overrides = parse_env_overrides(args.env)
    env.update(overrides)

    if args.codex_path:
        env["CODEX_PATH"] = args.codex_path
    elif args.agent == "codex" and "CODEX_PATH" not in overrides:
        codex_bin = shutil.which("codex")
        if codex_bin:
            env.setdefault("CODEX_PATH", codex_bin)
    return env


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Headless Python ACP client demo.")
    parser.add_argument(
        "--agent",
        choices=sorted([*AGENT_REGISTRY.keys(), "custom"]),
        default="hermes",
        help="ACP agent adapter to run. Default: hermes",
    )
    parser.add_argument(
        "--command", help="Override adapter command, or required for --agent custom."
    )
    parser.add_argument(
        "--arg",
        action="append",
        help="Adapter argument. Repeat for multiple args. Used with --command/custom.",
    )
    parser.add_argument(
        "--cwd", default=os.getcwd(), help="Workspace cwd passed to ACP session."
    )
    parser.add_argument(
        "--env",
        action="append",
        help="Environment override for the ACP adapter process, as KEY=VALUE. Repeat for multiple vars.",
    )
    parser.add_argument(
        "--codex-path",
        help="Codex CLI path used by codex-acp. Defaults to the codex found on PATH.",
    )
    parser.add_argument(
        "--permission",
        choices=["deny", "allow", "ask"],
        default="deny",
        help="Permission policy for ACP permission requests. Default: deny",
    )
    parser.add_argument(
        "--timeout", type=float, default=900.0, help="Prompt timeout in seconds."
    )
    parser.add_argument(
        "--interactive",
        "-i",
        action="store_true",
        help="Keep process/session and prompt in a REPL.",
    )
    parser.add_argument(
        "--format", choices=["text", "json"], default="text", help="Output format."
    )
    parser.add_argument(
        "--verbose", "-v", action="store_true", help="Stream progress to stderr."
    )
    parser.add_argument(
        "--trace-acp",
        action="store_true",
        help="Print every raw ACP JSON-RPC message to stderr.",
    )
    parser.add_argument(
        "prompt", nargs="*", help="Prompt text. Omit with --interactive for REPL."
    )
    return parser


async def run_once(args: argparse.Namespace) -> int:
    command, adapter_args = resolve_command(args)
    adapter_env = build_adapter_env(args)
    prompt = " ".join(args.prompt).strip()
    if not prompt:
        raise SystemExit("prompt is required unless --interactive is used")
    cwd = Path(args.cwd).expanduser().resolve()
    async with AcpAgentRunner(
        name=args.agent,
        command=command,
        args=adapter_args,
        cwd=cwd,
        env=adapter_env,
        permission_policy=args.permission,
        verbose=args.verbose,
        trace_acp=args.trace_acp,
    ) as runner:
        try:
            result = await runner.prompt(prompt, cwd=cwd, timeout=args.timeout)
        except Exception as exc:
            await asyncio.sleep(0.2)
            emit_error(exc, args.format, runner._stderr_tail)
            return 1
        emit_result(result, args.format)
    return 0


async def run_interactive(args: argparse.Namespace) -> int:
    command, adapter_args = resolve_command(args)
    adapter_env = build_adapter_env(args)
    cwd = Path(args.cwd).expanduser().resolve()
    async with AcpAgentRunner(
        name=args.agent,
        command=command,
        args=adapter_args,
        cwd=cwd,
        env=adapter_env,
        permission_policy=args.permission,
        verbose=args.verbose,
        trace_acp=args.trace_acp,
    ) as runner:
        initial = " ".join(args.prompt).strip()
        if initial:
            try:
                result = await runner.prompt(initial, cwd=cwd, timeout=args.timeout)
                emit_result(result, args.format)
            except Exception as exc:
                await asyncio.sleep(0.2)
                emit_error(exc, args.format, runner._stderr_tail)

        print(
            f"ACP interactive session started for {args.agent}. Type /exit to quit.",
            file=sys.stderr,
        )
        while True:
            try:
                text = input("acp> ").strip()
            except (EOFError, KeyboardInterrupt):
                print("", file=sys.stderr)
                break
            if text in {"/exit", "/quit"}:
                break
            if not text:
                continue
            try:
                result = await runner.prompt(text, cwd=cwd, timeout=args.timeout)
                emit_result(result, args.format)
            except Exception as exc:
                await asyncio.sleep(0.2)
                emit_error(exc, args.format, runner._stderr_tail)
    return 0


def emit_result(result: dict[str, Any], output_format: str) -> None:
    if output_format == "json":
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return

    text = result.get("final_text") or ""
    if text:
        print(text)
    else:
        print("(no agent message received)")
        stderr_tail = result.get("stderr_tail") or []
        if stderr_tail:
            print("\nAdapter stderr tail:", file=sys.stderr)
            print("\n".join(stderr_tail[-10:]), file=sys.stderr)


def emit_error(exc: Exception, output_format: str, stderr_tail: list[str]) -> None:
    error: dict[str, Any] = {
        "error": type(exc).__name__,
        "message": str(exc),
        "stderr_tail": list(stderr_tail[-50:]),
    }
    code = getattr(exc, "code", None)
    data = getattr(exc, "data", None)
    if code is not None:
        error["code"] = code
    if data is not None:
        error["data"] = _dump_model(data)

    if output_format == "json":
        print(json.dumps(error, ensure_ascii=False, indent=2), file=sys.stderr)
        return

    print(f"ACP request failed: {error['message']} ({error['error']})", file=sys.stderr)
    if code is not None:
        print(f"JSON-RPC code: {code}", file=sys.stderr)
    if data is not None:
        print(
            f"JSON-RPC data: {json.dumps(error['data'], ensure_ascii=False)}",
            file=sys.stderr,
        )
    if stderr_tail:
        print("\nAdapter stderr tail:", file=sys.stderr)
        print("\n".join(stderr_tail[-20:]), file=sys.stderr)


async def amain(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    if args.verbose:
        command, adapter_args = resolve_command(args)
        print(f"Adapter: {shlex.join([command, *adapter_args])}", file=sys.stderr)
        env = build_adapter_env(args)
        codex_path = env.get("CODEX_PATH", "")
        if codex_path:
            print(f"CODEX_PATH: {codex_path}", file=sys.stderr)
    if args.interactive:
        return await run_interactive(args)
    return await run_once(args)


def main() -> None:
    try:
        raise SystemExit(asyncio.run(amain()))
    except ModuleNotFoundError as exc:
        if exc.name == "acp":
            print(
                "Missing dependency: agent-client-protocol. Install with:\n"
                "  python3 -m pip install -r requirements.txt",
                file=sys.stderr,
            )
            raise SystemExit(2) from exc
        raise


if __name__ == "__main__":
    main()
