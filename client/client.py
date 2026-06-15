"""Entry point for the Bridge-Client gateway.

Runs the OpenAI-compatible FastAPI gateway on the configured PORT.

Usage:
    python -m client.client
    # or from repo root:
    python client/client.py
"""
import os
import sys

# Ensure imports work when running as a script (python client/client.py).
if __name__ == "__main__" and __package__ is None:
    sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import uvicorn

from client.config import settings
from client.gateway import app

if __name__ == "__main__":
    print(f"[Bridge-Client] Starting gateway on {settings.host}:{settings.port}")
    print(f"[Bridge-Client] Bridge-Server URL: {settings.bridge_server_url}")
    uvicorn.run(app, host=settings.host, port=settings.port)
