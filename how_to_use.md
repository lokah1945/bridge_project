# 🌉 Bridge-Gateway: Enterprise Automation Architecture

Sistem ini adalah replika fungsional 1:1 dari Web UI provider AI (Arena, Qwen, DeepSeek) ke dalam API OpenAI-compatible.

## 🏗️ Arsitektur: Hub-and-Spoke Automation
Sistem ini menggunakan pemisahan tanggung jawab yang ketat untuk memastikan bypass deteksi bot dan efisiensi eksekusi.

### 1. Bridge-Server (The Session Hub)
- **Lokasi**: Windows Server (Headfull Browser).
- **Tanggung Jawab**: 
    - Melakukan autentikasi manual.
    - Menjaga session browser tetap hidup.
    - Menyediakan Cookies & Headers melalui endpoint `/get-session`.
- **Kunci**: Menggunakan CDP Stealth untuk memastikan session valid dan tidak terdeteksi sebagai bot.

### 2. Bridge-Client (The Automation Engine)
- **Lokasi**: Linux / Server.
- **Tanggung Jawab**:
    - **Session Manager**: Mengambil, mengenkripsi (AES-256), dan menyimpan session lokal.
    - **Automation Executor**: Meluncurkan browser headless, menginjeksi session, dan melakukan simulasi interaksi DOM.
    - **Model Cache System**: Mengotomatisasi discovery model setiap 60 menit dan menyimpannya di `model.json`.
    - **OpenAI Gateway**: Menyediakan endpoint `/v1/chat/completions`.

## 🛠️ Deployment & Konfigurasi

### Konfigurasi `.env` (Client)
```env
BRIDGE_SERVER_URL=http://<windows-ip>:9877
PORT=8000
ENCRYPTION_KEY=<your-fernet-key>
SESSION_TTL_HOURS=24
```

## 🚀 Panduan Penggunaan & Fitur

### Model Discovery (Stateless Cache)
Model tidak lagi dicari setiap kali request. Sistem menggunakan `model.json` yang diperbarui setiap 1 jam via background task.
- **Cache File**: `model.json`
- **Update Cycle**: 60 Menit.

### Format Model Call
`bridge/<provider>/<modality>/<model_id>` (Modality hanya untuk Arena)

### Matrix Fitur & Parameter (`extra_params`)

| Provider | Parameter | Nilai | Efek |
| :--- | :--- | :--- | :--- |
| **Arena** | `temporary_chat` | `true` | **Stateless Mode**: Tanpa riwayat akun. |
| **Qwen** | `thinking` | `auto`, `thinking`, `fast` | Kontrol CoT Reasoning. |
| **Qwen** | `tools` | `true`, `false` | Aktivasi Web Search/Tools. |
| **DeepSeek**| `mode` | `fast`, `expert` | Kontrol Latency vs Reasoning. |
| **DeepSeek**| `thinking` | `true`, `false` | Aktifkan Thought Process. |
| **DeepSeek**| `search` | `true`, `false` | Aktifkan Web Search. |

## 🛡️ Jaminan Kualitas (QA)
- **100% Stateless**: Implementasi navigasi direct dan pembersihan session.
- **100% Stealth**: Override navigator.webdriver dan header CDP di level engine.
- **1:1 Parity**: Eksekusi berbasis DOM, bukan asumsi API.
