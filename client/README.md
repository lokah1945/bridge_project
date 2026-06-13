# 📱 Bridge-Client (Persistence Mode) - Installation Guide

This client uses a **State-Persistence** mechanism. It syncs sessions from the Bridge-Server once and stores them locally.

## 🚀 How it Works
1. **Sync:** The client contacts `BRIDGE_SERVER_URL` to get cookies.
2. **Cache:** Cookies are saved in the `/sessions` folder.
3. **Offline Execution:** Once synced, the client no longer needs the server to be online to make requests.
4. **Auto-Refresh:** If a request fails due to authorization, the client automatically attempts to re-sync with the server.

## 🛠️ Installation
1. `pip install -r requirements.txt`
2. Edit `.env` $\rightarrow$ `BRIDGE_SERVER_URL=http://host.zerotier.my.id:9877`

## ⚡ Usage
```python
from client import BridgeClient
import asyncio

async def run():
    client = BridgeClient()
    # Will sync from server on first run, then use local cache
    res = await client.call_bridge("bridge/arena/gpt-4o", {"messages": [...]})
    print(res)

asyncio.run(run())
```
