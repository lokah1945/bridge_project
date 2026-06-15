
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import StreamingResponse
import json
import asyncio
from engine import ArenaEngine

app = FastAPI(title="Bridge-Arena OpenAI Gateway")
engine = ArenaEngine()

@app.on_event("startup")
async def startup_event():
    await engine.start()

@app.get("/v1/models")
async def list_models():
    models = await engine.get_models()
    return {
        "object": "list",
        "data": [{"id": m, "object": "model", "owned_by": "arena"} for m in models]
    }

@app.post("/v1/chat/completions")
async def chat_completions(request: Request):
    body = await request.json()
    model = body.get("model", "Default")
    messages = body.get("messages", [])
    stream = body.get("stream", False)
    
    if not messages:
        raise HTTPException(status_code=400, detail="No messages provided")
    
    prompt = messages[-1]["content"]
    
    if stream:
        async def event_generator():
            async for chunk in engine.chat_stream(model, prompt):
                # OpenAI Stream Format
                data = {
                    "id": "chatcmpl-arena",
                    "object": "chat.completion.chunk",
                    "created": 0,
                    "model": model,
                    "choices": [{"index": 0, "delta": {"content": chunk}, "finish_reason": None}]
                }
                yield f"data: {json.dumps(data)}\n\n"
            yield "data: [DONE]\n\n"
            
        return StreamingResponse(event_generator(), media_type="text/event-stream")
    else:
        # Collect all chunks for non-stream
        full_response = ""
        async for chunk in engine.chat_stream(model, prompt):
            full_response += chunk
            
        return {
            "id": "chatcmpl-arena",
            "object": "chat.completion",
            "created": 0,
            "model": model,
            "choices": [{
                "index": 0,
                "message": {"role": "assistant", "content": full_response},
                "finish_reason": "stop"
            }]
        }

@app.get("/health")
async def health():
    return {"status": "ready", "engine": "active"}

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)
