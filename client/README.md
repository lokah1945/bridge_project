# 📱 Bridge-Client (OpenAI-Compatible Gateway)

This package is the automation engine and gateway for the Bridge-Project.

## Files

- `client.py` — entry point to start the FastAPI gateway.
- `config.py` — centralized configuration loaded from `.env`.
- `session_manager.py` — fetch, encrypt, and cache bridge-server sessions.
- `browser_manager.py` — Playwright lifecycle, stealth, and context-per-request isolation.
- `model_cache.py` — background model discovery and `model.json` cache.
- `gateway.py` — FastAPI app with `/v1/chat/completions`, `/v1/models`, `/health`.
- `cli.py` — HTTP-based CLI for one-shot and interactive chat.

## Start the Gateway

```bash
python client/client.py
```

## Use the CLI

```bash
python -m client.cli models
python -m client.cli chat -m bridge/qwen/qwen-max "Hello"
python -m client.cli chat -m bridge/deepseek/deepseek-v3 -i
```

## Programmatic Example

```python
import asyncio
from client.session_manager import SessionManager
from providers.qwen import QwenProvider

async def main():
    session = await SessionManager().get_effective_session("qwen")
    provider = QwenProvider(session)
    response = await provider.execute("qwen-max", "Hello", {"thinking": "fast"})
    print(response)
    await provider.cleanup()

asyncio.run(main())
```
