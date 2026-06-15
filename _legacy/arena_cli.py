
import requests
import argparse
import sys
import json

def main():
    parser = argparse.ArgumentParser(description="Arena Direct Local CLI")
    parser.add_argument("command", choices=["models", "ask", "health"])
    parser.add_argument("--model", type=str, help="Model name to use")
    parser.add_argument("--prompt", type=str, help="Prompt to send")
    
    args = parser.parse_args()
    base_url = "http://localhost:8000"

    if args.command == "health":
        res = requests.get(f"{base_url}/health")
        print(f"Status: {res.json()['status']}")
        
    elif args.command == "models":
        res = requests.get(f"{base_url}/v1/models")
        models = [m["id"] for m in res.json()["data"]]
        print("Available Models:\n" + "\n".join(models))
        
    elif args.command == "ask":
        if not args.model or not args.prompt:
            print("Error: --model and --prompt are required")
            sys.exit(1)
            
        payload = {
            "model": args.model,
            "messages": [{"role": "user", "content": args.prompt}],
            "stream": True
        }
        
        with requests.post(f"{base_url}/v1/chat/completions", json=payload, stream=True) as r:
            for line in r.iter_lines():
                if line:
                    decoded_line = line.decode('utf-8')
                    if decoded_line == "data: [DONE]":
                        break
                    if decoded_line.startswith("data: "):
                        data = json.loads(decoded_line[6:])
                        content = data["choices"][0]["delta"].get("content", "")
                        print(content, end="", flush=True)
            print()

if __name__ == "__main__":
    main()
