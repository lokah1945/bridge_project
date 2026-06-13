# 🗺️ Bridge-Server Comprehensive Model & Feature Map

Dokumen ini adalah referensi utama untuk memanggil model melalui Bridge-Client dengan kontrol fitur mendalam.

## 🚀 Global API Format
**Endpoint:** `POST /v1/chat/completions`
**Payload:**
```json
{
  "model": "bridge/<provider>/<model_id>",
  "messages": [{"role": "user", "content": "..."}],
  "extra_params": {
    "feature_name": "value"
  }
}
```

---

## 🎨 Arena.ai
Sistem routing berdasarkan modalitas.

| Modality | Model Identifier | Format Call | `extra_params` | Note |
| :--- | :--- | :--- | :--- | :--- |
| **Text** | `gpt-4o`, `claude-3-5-sonnet` | `bridge/arena/text/<model>` | `{"temporary_chat": bool}` | `True` = Zero History |
| **Search** | `perplexity-sonar`, `gpt-4o-search` | `bridge/arena/search/<model>` | `{"temporary_chat": bool}` | Web-enabled |
| **Image** | `dall-e-3`, `midjourney-v6` | `bridge/arena/image/<model>` | `{"aspect_ratio": "1:1"}` | Image Gen |
| **Code** | `deepseek-coder-v2` | `bridge/arena/code/<model>` | `{"temporary_chat": bool}` | Coding Optimized |

---

## 🐉 Qwen.ai
Mendukung model utama dan model "Expanded".

| Model Identifier | Format Call | `extra_params` | Note |
| :--- | :--- | :--- | :--- |
| **qwen-max** | `bridge/qwen/qwen-max` | `{"thinking": "auto"\|"thinking"\|"fast", "tools": bool}` | Flagship |
| **qwen-plus** | `bridge/qwen/qwen-plus` | `{"thinking": "...", "tools": bool}` | Balanced |
| **qwen-turbo** | `bridge/qwen/qwen-turbo` | `{"thinking": "...", "tools": bool}` | Fast |
| **qwen-72b-chat** | `bridge/qwen/qwen-72b-chat` | `{"thinking": "...", "tools": bool}` | Expanded List |

**Qwen Feature Guide:**
- `thinking`: 
  - `auto`: Model menentukan kapan harus berpikir.
  - `thinking`: Paksa model menggunakan reasoning (CoT).
  - `fast`: Lewati reasoning untuk respons instan.
- `tools`: `True` (Aktifkan plugin/web), `False` (Matikan).

---

## 🧬 DeepSeek
Fokus pada kontrol kualitas reasoning.

| Model Identifier | Format Call | `extra_params` | Note |
| :--- | :--- | :--- | :--- |
| **deepseek-v3** | `bridge/deepseek/deepseek-v3` | `{"mode": "fast"\|"expert", "thinking": bool, "search": bool}` | Generalist |
| **deepseek-coder** | `bridge/deepseek/deepseek-coder` | `{"mode": "...", "thinking": bool, "search": bool}` | Coding |

**DeepSeek Feature Guide:**
- `mode`: `fast` (Low latency) atau `expert` (Deep reasoning).
- `thinking`: `True` (Aktifkan mode berpikir), `False` (Direct response).
- `search`: `True` (Aktifkan Web Search), `False` (Knowledge base saja).
