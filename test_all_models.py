
import asyncio
import httpx
import json

async def test_model(model_id):
    url = "http://localhost:8000/v1/chat/completions"
    payload = {
        "model": model_id,
        "messages": [{"role": "user", "content": "hallo"}],
        "extra_params": {
            "temporary_chat": True,
            "thinking": "fast"
        }
    }
    
    print(f"[*] Testing {model_id}...", end=" ", flush=True)
    try:
        async with httpx.AsyncClient(timeout=120.0) as client:
            resp = await client.post(url, json=payload)
            if resp.status_code == 200:
                content = resp.json()["choices"][0]["message"]["content"]
                print(f"✅ SUCCESS | Reply: {content[:50]}...")
                return True
            else:
                print(f"❌ FAILED | Status: {resp.status_code} | Error: {resp.text}")
                return False
    except Exception as e:
        print(f"❌ ERROR | {str(e)}")
        return False

async def main():
    models = [
        "bridge/arena/text/gpt-4o",
        "bridge/arena/text/claude-3-5-sonnet",
        "bridge/arena/search/perplexity-sonar",
        "bridge/qwen/qwen-max",
        "bridge/qwen/qwen-plus",
        "bridge/deepseek/deepseek-v3",
        "bridge/deepseek/deepseek-coder",
    ]
    
    results = []
    for m in models:
        success = await test_model(m)
        results.append(success)
    
    print("\n=== FINAL REPORT ===")
    print(f"Total Models: {len(models)}")
    print(f"Successful: {sum(results)}")
    print(f"Failed: {len(models) - sum(results)}")
    
    if sum(results) == len(models):
        print("\n🎯 RESULT: 100% FUNCTIONAL")
    else:
        print("\n⚠️ RESULT: NEEDS ITERATION")

if __name__ == "__main__":
    asyncio.run(main())
