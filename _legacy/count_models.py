
import asyncio
import httpx
import os
from dotenv import load_dotenv
from providers.arena import ArenaProvider
from providers.qwen import QwenProvider
from providers.deepseek import DeepSeekProvider

load_dotenv()

BRIDGE_SERVER_URL = os.getenv("BRIDGE_SERVER_URL", "http://host.zerotier.my.id:9877")

async def get_session(provider):
    async with httpx.AsyncClient() as client:
        resp = await client.get(f"{BRIDGE_SERVER_URL}/get-session/{provider}")
        return resp.json()

async def main():
    print("🔍 Starting Dynamic Model Discovery...")
    
    # 1. Arena
    print("[*] Counting Arena models...")
    try:
        arena_session = await get_session("arena")
        arena_prov = ArenaProvider(arena_session)
        total_arena = 0
        for mod in ArenaProvider.MODALITIES.keys():
            models = await arena_prov.list_models(modality=mod)
            print(f"  - {mod}: {len(models)} models")
            total_arena += len(models)
        print(f"Total Arena: {total_arena}")
        await arena_prov.cleanup()
    except Exception as e:
        print(f"Arena Error: {e}")

    # 2. Qwen
    print("[*] Counting Qwen models...")
    try:
        qwen_session = await get_session("qwen")
        qwen_prov = QwenProvider(qwen_session)
        models = await qwen_prov.list_models()
        print(f"Total Qwen: {len(models)}")
        await qwen_prov.cleanup()
    except Exception as e:
        print(f"Qwen Error: {e}")

    # 3. DeepSeek
    print("[*] Counting DeepSeek models...")
    try:
        ds_session = await get_session("deepseek")
        ds_prov = DeepSeekProvider(ds_session)
        models = await ds_prov.list_models()
        print(f"Total DeepSeek: {len(models)}")
        await ds_prov.cleanup()
    except Exception as e:
        print(f"DeepSeek Error: {e}")

if __name__ == "__main__":
    asyncio.run(main())
