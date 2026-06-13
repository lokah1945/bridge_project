
import json
from datetime import datetime

def bootstrap():
    print("🚀 Bootstrapping model.json (Seed Mode)...")
    
    seeds = {
        "arena": {
            "text": ["gpt-4o", "claude-3-5-sonnet"],
            "search": ["perplexity-sonar"],
            "image": ["dall-e-3"],
            "code": ["deepseek-coder-v2"]
        },
        "qwen": ["qwen-max", "qwen-plus", "qwen-turbo"],
        "deepseek": ["deepseek-v3", "deepseek-coder"]
    }

    all_models = []
    # Arena
    for mod, models in seeds["arena"].items():
        for m in models:
            all_models.append({"id": f"bridge/arena/{mod}/{m}", "object": "model", "provider": "arena"})
    # Qwen
    for m in seeds["qwen"]:
        all_models.append({"id": f"bridge/qwen/{m}", "object": "model", "provider": "qwen"})
    # DeepSeek
    for m in seeds["deepseek"]:
        all_models.append({"id": f"bridge/deepseek/{m}", "object": "model", "provider": "deepseek"})

    with open("model.json", "w") as f:
        json.dump({
            "last_updated": datetime.now().isoformat(),
            "models": all_models
        }, f, indent=2)
    
    print(f"✅ Successfully seeded {len(all_models)} models into model.json")

if __name__ == "__main__":
    bootstrap()
