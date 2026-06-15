"""CLI client for Bridge-Client gateway.

Usage:
  bridge-cli models [--refresh]
  bridge-cli chat -m <model> [--system "..."] [--stream/--no-stream] [--param key=value ...] "<prompt>"
  bridge-cli chat -m <model> -i
  bridge-cli session status
  bridge-cli session refresh
  bridge-cli health

Environment variables:
  BRIDGE_API_BASE_URL (default: http://127.0.0.1:8000)
  BRIDGE_API_KEY      (optional, required if gateway API_KEY is set)
"""
import argparse
import json
import os
import sys
from typing import Any, Dict, List, Optional

import httpx
from rich import box
from rich.console import Console
from rich.markdown import Markdown
from rich.table import Table

from client.config import settings

console = Console()

DEFAULT_BASE_URL = os.getenv("BRIDGE_API_BASE_URL") or f"http://127.0.0.1:{settings.port}"


def _api_key() -> Optional[str]:
    return os.getenv("BRIDGE_API_KEY") or settings.api_key


def _headers() -> Dict[str, str]:
    headers = {"Content-Type": "application/json"}
    key = _api_key()
    if key:
        headers["Authorization"] = f"Bearer {key}"
    return headers


def _handle_http_error(e: httpx.HTTPStatusError) -> None:
    try:
        detail = e.response.json().get("detail", e.response.text)
    except Exception:
        detail = e.response.text
    console.print(f"[red]Error {e.response.status_code}: {detail}[/red]")


def cmd_health(base_url: str) -> int:
    try:
        resp = httpx.get(f"{base_url}/health", headers=_headers(), timeout=10.0)
        resp.raise_for_status()
    except httpx.HTTPStatusError as e:
        _handle_http_error(e)
        return 1
    except Exception as e:
        console.print(f"[red]Failed to reach health endpoint: {e}[/red]")
        return 1

    data = resp.json()
    console.print_json(data=data)
    return 0


def cmd_models(base_url: str, refresh: bool = False) -> int:
    try:
        if refresh:
            try:
                httpx.post(f"{base_url}/v1/models/refresh", headers=_headers(), timeout=30.0)
            except Exception:
                pass
        resp = httpx.get(f"{base_url}/v1/models", headers=_headers(), timeout=30.0)
        resp.raise_for_status()
    except httpx.HTTPStatusError as e:
        _handle_http_error(e)
        return 1
    except Exception as e:
        console.print(f"[red]Failed to fetch models: {e}[/red]")
        return 1

    data = resp.json().get("data", [])
    if not data:
        console.print("[yellow]No models found in cache.[/yellow]")
        return 0

    table = Table(title="Available Models", box=box.ROUNDED)
    table.add_column("ID", style="cyan", no_wrap=True)
    table.add_column("Provider", style="green")
    table.add_column("Modality", style="yellow")

    for m in data:
        model_id = m.get("id", "")
        owned_by = m.get("owned_by", "")
        modality = m.get("modality", "")
        table.add_row(model_id, owned_by, modality)

    console.print(table)
    return 0


def _parse_extra_params(params: List[str]) -> Dict[str, Any]:
    result: Dict[str, Any] = {}
    for p in params:
        if "=" not in p:
            console.print(f"[red]Invalid --param format: {p} (expected key=value)[/red]")
            sys.exit(1)
        key, value = p.split("=", 1)
        if value.lower() in ("true", "false"):
            value = value.lower() == "true"
        else:
            try:
                if "." in value:
                    value = float(value)
                else:
                    value = int(value)
            except ValueError:
                pass
        result[key] = value
    return result


def _send_chat(
    base_url: str,
    model: str,
    messages: List[Dict[str, str]],
    extra_params: Dict[str, Any],
    stream: bool,
) -> str:
    payload = {
        "model": model,
        "messages": messages,
        "extra_params": extra_params,
        "stream": stream,
    }

    with httpx.Client(timeout=180.0) as client:
        try:
            resp = client.post(
                f"{base_url}/v1/chat/completions",
                json=payload,
                headers=_headers(),
                stream=stream,
            )
            resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            _handle_http_error(e)
            return ""

        if stream:
            full = ""
            for line in resp.iter_lines():
                if not line:
                    continue
                if line.startswith("data: "):
                    data = line[6:]
                    if data == "[DONE]":
                        break
                    try:
                        chunk = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                    delta = chunk.get("choices", [{}])[0].get("delta", {}).get("content", "")
                    finish_reason = chunk.get("choices", [{}])[0].get("finish_reason")
                    if delta:
                        console.print(delta, end="")
                        full += delta
                    if finish_reason:
                        console.print()
                        break
            return full
        else:
            data = resp.json()
            content = data["choices"][0]["message"]["content"]
            return content


def cmd_chat(
    model: str,
    prompt: Optional[str],
    system: Optional[str],
    interactive: bool,
    stream: bool,
    extra_params: Dict[str, Any],
    base_url: str,
) -> int:
    messages: List[Dict[str, str]] = []
    if system:
        messages.append({"role": "system", "content": system})

    if not interactive:
        if not prompt:
            console.print("[red]Prompt required in non-interactive mode.[/red]")
            return 1
        messages.append({"role": "user", "content": prompt})
        content = _send_chat(base_url, model, messages, extra_params, stream)
        if content and not stream:
            console.print(Markdown(content))
        return 0 if content else 1

    console.print(f"[bold green]Interactive chat with {model}[/bold green]")
    console.print("[dim]Type /exit to quit, /reset to clear history[/dim]")
    while True:
        try:
            user_input = console.input("[bold blue]You:[/bold blue] ")
        except (EOFError, KeyboardInterrupt):
            console.print("\n[yellow]Exiting.[/yellow]")
            break
        cmd = user_input.strip().lower()
        if cmd in ("exit", "quit", "/exit"):
            break
        if cmd == "/reset":
            messages = []
            if system:
                messages.append({"role": "system", "content": system})
            console.print("[yellow]History reset.[/yellow]")
            continue
        messages.append({"role": "user", "content": user_input})
        console.print("[bold green]Assistant:[/bold green] ", end="")
        assistant = _send_chat(base_url, model, messages, extra_params, stream)
        if assistant and not stream:
            console.print(Markdown(assistant))
        if assistant:
            messages.append({"role": "assistant", "content": assistant})
    return 0


def cmd_session(base_url: str, action: str) -> int:
    if action == "status":
        try:
            resp = httpx.get(f"{base_url}/health", headers=_headers(), timeout=10.0)
            resp.raise_for_status()
        except httpx.HTTPStatusError as e:
            _handle_http_error(e)
            return 1
        except Exception as e:
            console.print(f"[red]Failed: {e}[/red]")
            return 1
        data = resp.json()
        console.print("[bold]Session status[/bold]")
        console.print_json(data=data.get("provider_status", {}))
        return 0

    if action == "refresh":
        console.print("[yellow]Manual session refresh is performed by the server background loop. "
                      "Restart the gateway to force a refresh.[/yellow]")
        return 0

    return 1


def main() -> int:
    parser = argparse.ArgumentParser(description="Bridge-Client CLI")
    parser.add_argument("--base-url", default=DEFAULT_BASE_URL, help="Gateway base URL")
    parser.add_argument("--api-key", default=None, help="API key (or use BRIDGE_API_KEY env)")
    subparsers = parser.add_subparsers(dest="command", required=True)

    subparsers.add_parser("health", help="Check gateway health")

    models_parser = subparsers.add_parser("models", help="List available models")
    models_parser.add_argument("--refresh", action="store_true", help="Trigger cache refresh first")

    chat_parser = subparsers.add_parser("chat", help="Send a chat request")
    chat_parser.add_argument("-m", "--model", required=True, help="Model ID, e.g. bridge/qwen/qwen-max")
    chat_parser.add_argument("prompt", nargs="?", help="Prompt text (for one-shot mode)")
    chat_parser.add_argument("-i", "--interactive", action="store_true", help="Interactive REPL mode")
    chat_parser.add_argument("--system", help="System prompt")
    chat_parser.add_argument("--stream", action="store_true", default=True, help="Stream response")
    chat_parser.add_argument("--no-stream", dest="stream", action="store_false", help="Non-stream response")
    chat_parser.add_argument(
        "--param",
        action="append",
        default=[],
        help="Extra params as key=value (repeatable)",
    )

    session_parser = subparsers.add_parser("session", help="Session management")
    session_parser.add_argument("action", choices=["status", "refresh"], help="Session action")

    args = parser.parse_args()

    if args.api_key:
        os.environ["BRIDGE_API_KEY"] = args.api_key

    if args.command == "health":
        return cmd_health(args.base_url)
    elif args.command == "models":
        return cmd_models(args.base_url, refresh=args.refresh)
    elif args.command == "chat":
        extra_params = _parse_extra_params(args.param)
        return cmd_chat(
            model=args.model,
            prompt=args.prompt,
            system=args.system,
            interactive=args.interactive,
            stream=args.stream,
            extra_params=extra_params,
            base_url=args.base_url,
        )
    elif args.command == "session":
        return cmd_session(args.base_url, args.action)
    return 0


if __name__ == "__main__":
    sys.exit(main())
