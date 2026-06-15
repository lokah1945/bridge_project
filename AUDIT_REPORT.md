# Audit Report — Bridge-Project Client Rebuild

> Tanggal audit: 2026-06-15  
> Repo: https://github.com/lokah1945/bridge_project  
> Tujuan: Audit, debug, dan rebuild komponen **bridge-client** agar Arena.ai, Qwen.ai, dan DeepSeek bisa diakses via OpenAI-compatible API (`/v1/chat/completions`, `/v1/models`) dan CLI.

---

## 1. Struktur Repo — File & Folder

### 1.1 Folder Resmi (sesuai README)

| Folder/File | Fungsi menurut README | Status temuan |
|-------------|-----------------------|---------------|
| `client/` | Entry point bridge-client (`python client/client.py`) | **Ada implementasi gateway terintegrasi** dengan SessionManager, model cache, dan FastAPI. |
| `server/` | Bridge-Server Node.js (session hub) | `server.js` adalah implementasi aktif yang sesuai port `.env.example` (9877). |
| `providers/` | Kelas provider (`base`, `arena`, `qwen`, `deepseek`) | Ada, digunakan oleh `client/client.py` dan `registry.py`. |
| `discovery/` | Logika scraping model (Model Cache System) | Berisi `discovery_probe.py` (standalone, pakai `playwright_extra`), tapi **tidak di-import** oleh `client/client.py`. |

### 1.2 File Root — Prototipe / Eksperimen

File di root mayoritas adalah **skrip eksplorasi/prototipe yang tidak di-import oleh `client/client.py`**:

| File | Keterangan | Digunakan client? | Rekomendasi |
|------|------------|-------------------|-------------|
| `bridge_server.py` | Prototipe Python/FastAPI bridge-server port 99876 | Tidak | Pindah ke `_legacy/` atau hapus. |
| `gateway.py` | Prototipe gateway Arena-only (root), beda dengan `client/client.py` | Tidak | Pindah ke `_legacy/`. |
| `engine.py` | Prototipe `ArenaEngine` — berisi banyak bug (BUG-1 s/d BUG-10 di master prompt) | Tidak | Pindah ke `_legacy/`. |
| `registry.py` | Registry provider, di-import `client/client.py` | **Ya** | Pertahankan / sempurnakan. |
| `arena_cli.py` | CLI sederhana untuk root gateway | Tidak | Pindah ke `_legacy/` atau hapus. |
| `count_models.py` | Skrip hitung model untuk test | Tidak | Pindah ke `_legacy/`. |
| `discovery_mini.py`, `discovery_probe.py`, `discovery_probe_simple.py` | Skrip scraping eksperimen | Tidak | Pindah ke `_legacy/`. |
| `dom_probe.py`, `dump_text.py` | DOM probing Arena | Tidak | Pindah ke `_legacy/`. |
| `test_all_models.py` | Test endpoint lokal | Tidak | Pindah ke `_legacy/` atau `tests/`. |
| `bootstrap_cache.py` | Seed `model.json` statis | Tidak | Pindah ke `_legacy/`. |
| `bridge-all.zip`, `bridge-arena.zip` | Arsip binary | Tidak | Hapus. |
| `*.log`, `*.png`, `*.html`, `chat_history.txt`, `network_requests.txt` | Log/debug artefak | Tidak | Tambah ke `.gitignore` dan hapus dari git history. |

### 1.3 Cross-Reference (siapa import siapa)

```text
client/client.py  -> registry.py, providers.{arena,qwen,deepseek}
bridge_server.py  -> registry.py, providers.base
registry.py       -> providers.base
gateway.py        -> engine.py (root)
arena_cli.py      -> requests (ke localhost:8000)
count_models.py   -> providers.{arena,qwen,deepseek}
```

Kesimpulan: **hanya `client/client.py`, `registry.py`, dan `providers/` yang masuk jalur produksi**. Sisanya bisa dipindahkan tanpa merusak sistem.

---

## 2. Implementasi Bridge-Server yang Aktif

Terdapat **dua kandidat bridge-server** di repo:

### 2.1 `server/server.js` (Node.js / Express)
- Port default: **9877** (sesuai `.env.example`)
- Cara jalan: `cd server && npm install && node server.js`
- Menggunakan `playwright-extra` + `puppeteer-extra-plugin-stealth`
- Launch `launchPersistentContext(profileDir)` — headfull default, kecuali `BROWSER_HEADLESS=true`
- Endpoint `/get-session/:provider` mengembalikan:
  ```js
  {
    "cookies": [...],           // live dari browserContext.cookies()
    "user_agent": "Mozilla/5.0 ...",
    "headers": { "Accept-Language": "..." }
  }
  ```
- **Kekurangan nyata**: `sessionStore` hardcode hanya untuk `arena` dan `qwen`; **tidak ada `deepseek`**. `user_agent` qwen adalah literal `"..."` (placeholder). Login manual; tidak ada mekanisme otomatis load session/login tersimpan.

### 2.2 `bridge_server.py` (Python / FastAPI)
- Port: **99876**
- `browser_context["sessions"]` berisi placeholder statis:
  - `cookies: []` kosong
  - `user_agent: "Mozilla/5.0..."` literal tidak lengkap
  - Tidak ada `deepseek`
- **Tidak pernah membaca cookie dari context aktif** (`browser_context["context"]`) sebelum `/get-session/{provider}`.
- Launch browser headless=False tanpa proses login.
- Endpoint `/invoke` memanggil `provider_class(session_data).handle_request(model_id, payload)` — tapi `BaseProvider` tidak punya method `handle_request` (hanya `execute` dan `list_models`).

### Rekomendasi Server
- **Server yang aktif kemungkinan besar adalah `server/server.js`**, karena cocok dengan `.env.example` (`BRIDGE_SERVER_URL=...:9877`) dan `server/README.md`.
- `bridge_server.py` adalah prototipe yang tidak pernah dijalankan dalam produksi (berbeda port, placeholder sessions).
- Perbaikan di sisi **server** (menambah `deepseek`, memperbaiki user_agent qwen) perlu dilakukan agar bridge-client bisa fetch session lengkap untuk ketiga provider. Namun perbaikan ini harus dikonfirmasi user, sesuai catatan Bagian 8 Master Prompt.

---

## 3. Analisis `client/client.py` (Implementasi Aktual)

File ini jauh lebih lengkap dari prototipe root, tetapi masih mengandung bug serius yang perlu diperbaiki.

### 3.1 Yang Sudah Benar/Baik
- Menggunakan `python-dotenv` dan `cryptography.Fernet` → enkripsi AES-256 sudah ada.
- `SessionManager` fetch dari `/get-session/{provider}`, encrypt, simpan `sessions/{provider}.bin`, cek TTL via `SESSION_TTL_HOURS`.
- Model cache: background task setiap 3600 detik, menulis `model.json`.
- Multi-provider dispatch via `registry` untuk `arena`, `qwen`, `deepseek`.
- FastAPI endpoint `/v1/chat/completions` dan `/v1/models` sudah ada.
- `created` timestamp di `chat_completions` sudah benar (int(datetime.now().timestamp())).

### 3.2 Bug & Kekurangan Utama di `client/client.py`

| # | Masalah | Dampak | Severity |
|---|---------|--------|----------|
| 1 | `chat_completions` hanya mengambil `messages[-1]["content"]` → riwayat multi-turn dan system prompt HILANG. | Tidak memenuhi semantik OpenAI chat. | Tinggi |
| 2 | `execute(model_id, prompt, extra_params)` meneruskan **prompt string**, bukan `messages[]` lengkap. | Provider tidak bisa tahu system/user history. | Tinggi |
| 3 | Streaming mengirim **1 karakter per chunk** (`for char in res:`), bukan delta streaming nyata. | Format OpenAI streaming tidak valid; client SDK bisa gagal parse. | Tinggi |
| 4 | Tidak ada `finish_reason: "stop"` di chunk terakhir sebelum `[DONE]`. | SDK OpenAI menunggu `finish_reason` yang tidak pernah datang. | Tinggi |
| 5 | `execute()` mengembalikan `str` penuh, bukan `AsyncIterator[str]`. | Provider tidak bisa mengirim streaming real-time. | Tinggi |
| 6 | `chat_completions` membuat instance provider baru (`adapter = provider_cls(session)`) per request, lalu `await adapter.cleanup()` menutup browser. | Overhead besar, tidak cocok untuk concurrency, cleanup terlalu agresif. | Sedang |
| 7 | Tidak ada autentikasi API key (`Authorization: Bearer`). | Gateway terbuka publik jika di-expose. | Sedang |
| 8 | Tidak ada CORS/limit/rate-limit. | Integrasi browser frontend bisa bermasalah / rentan abuse. | Rendah |
| 9 | Model cache update menutup browser tiap provider (`adapter.cleanup()`), berpotensi gagal jika `list_models()` butuh waktu. | Kegagalan background cache silent. | Sedang |
| 10 | `messages` tidak divalidasi sebagai list of dict dengan `role`/`content`. | Request invalid bisa crash gateway. | Sedang |
| 11 | No `/health` endpoint (sebenarnya bisa ditambahkan). | Monitoring sederhana tidak ada. | Rendah |
| 12 | `client.py` terlalu monolitik (semua di satu file). | Sulit di-maintain/test. | Rendah |

### 3.3 Kontrak Provider Saat Ini

`BaseProvider` (di `providers/base.py`) punya signature:
```python
class BaseProvider(ABC):
    def __init__(self, session_data: Dict[str, Any]): ...
    async def _setup_browser(self) -> Page: ...
    async def list_models(self, **kwargs) -> List[str]: ...
    async def execute(self, model_id: str, prompt: str, params: Dict[str, Any]) -> str: ...
    async def cleanup(self): ...
```

Kekurangan:
- `execute()` mengembalikan `str` penuh, bukan `AsyncIterator[str]` untuk streaming.
- Tidak ada `chat_stream(messages, extra_params)`.
- `cleanup()` menutup `self.browser`, padahal sebaiknya browser/context di-pool/reuse.
- `_setup_browser()` membuat browser per-instance, tidak efisien.
- Stealth menggunakan `new_CDPSession(page)` lalu `Page.addScriptToEvaluateOnNewDocument`, tetapi tidak memakai `playwright-stealth` (yang sudah ada di `requirements.txt` root). `playwright-stealth` di root belum dipakai di kode manapun.

---

## 4. Perbandingan Kode Aktual vs. Master Prompt

| Poin Master Prompt | Kode Aktual | Status |
|--------------------|-------------|--------|
| Entry point `python client/client.py` | `client/client.py` exist | ✅ |
| Session Manager + Fernet AES-256 | `SessionManager` ada | ✅ |
| Model cache `model.json` 60 menit | `update_model_cache()` + loop 3600s ada | ✅ |
| Gateway `/v1/chat/completions` | Ada | ✅ tapi perlu perbaiki streaming |
| Gateway `/v1/models` | Ada | ✅ tapi baca dari cache |
| Multi-provider (arena, qwen, deepseek) | `registry` terdaftar | ✅ |
| CLI based chat AI | `arena_cli.py` root sederhana; belum ada `client/cli.py` modern | ❌ |
| Full `messages[]` history | Hanya `messages[-1]` yang dipakai | ❌ |
| `extra_params` dikonversi ke aksi DOM | `params` diteruskan, tetapi provider `execute()` hanya string prompt; DOM actions ada di `arena.py/qwen.py/deepseek.py` tapi perlu diuji | ⚠️ |
| Stateless / Zero Footprint | `cleanup()` hanya `clear_cookies()`; tidak navigate temporary endpoint setelah request | ⚠️ |
| 100% Stealth | `new_CDPSession` + addInitScript; `playwright-stealth` tidak dipakai | ⚠️ |
| Concurrency aman | Instance provider + browser per request; tidak ada lock/pool | ❌ |
| Timeout & retry | Timeout `wait_for_selector` ada (60s), tapi polling tidak ada max iteration | ❌ |
| Error taxonomy | Semua error jadi `HTTPException(500, detail=str(e))` | ❌ |

---

## 5. Temuan Server-Side yang Perlu Konfirmasi User

Sebelum rebuild bridge-client, beberapa hal di sisi server perlu dikonfirmasi karena client bergantung pada response `/get-session/{provider}`:

1. **Server mana yang aktif?** `server/server.js` (port 9877) atau `bridge_server.py` (port 99876)?  
   Asumsi audit: `server/server.js` karena cocok `.env.example`.

2. **Apakah `deepseek` sudah didaftarkan di `server.js`?** Saat ini `sessionStore` hanya `arena` dan `qwen`; client akan gagal fetch session untuk `deepseek` (404).

3. **Apakah user_agent untuk `qwen` di `server.js` valid?** Saat ini `sessionStore.qwen.user_agent` adalah `"..."` (placeholder).

4. **Apakah di Windows server sudah login manual untuk semua provider yang akan dipakai?** Karena client hanya menerima cookies; tanpa login, akses model premium bisa gagal.

---

## 6. Rekomendasi Rencana Rebuild (Fase 1-8)

Berikut ringkasan rencana rebuild berdasarkan hasil audit. Detail lengkap ada di Master Prompt Bagian 6.

### Fase 1 — Konfigurasi & Dependency
- Merge `client/requirements.txt` + `requirements.txt` root; tambah `cryptography`, `python-dotenv`, `httpx`, `pydantic-settings` (opsional), `apscheduler` (opsional). Pastikan `playwright-stealth` kompatibel.
- Buat `client/config.py` sentral (Pydantic Settings / `python-dotenv`).
- Perbaiki konflik port: hapus/abaikan `bridge_server.py` (port 99876), gunakan `server/server.js` (9877).

### Fase 2 — Session Manager
- Sempurnakan `client/session_manager.py`: fetch `/get-session/{provider}`, encrypt Fernet, simpan `sessions/{provider}.enc`, TTL auto-refresh, fallback ke cache lokal jika server sementara offline.
- Jika diizinkan, perbaiki `server/server.js` tambah `deepseek` dan perbaiki `user_agent` qwen.

### Fase 3 — Browser Manager & Stealth
- Buat `client/browser_manager.py`: satu Playwright browser instance, pool of contexts, inject cookies, apply stealth (CDP + `playwright-stealth`), semua context headless.
- Gunakan `asyncio.Semaphore` untuk limit concurrency (configurable via `.env`).

### Fase 4 — Provider Implementations
- Ubah kontrak `BaseProvider` jadi `chat_stream(model_id, messages, extra_params) -> AsyncIterator[str]`.
- Refactor/rebuild `providers/arena.py`, `providers/qwen.py`, `providers/deepseek.py` dengan:
  - Selector spesifik + fallback + logging.
  - Full message history (concat system + multi-turn).
  - `extra_params` → aksi DOM (temporary_chat, aspect_ratio, thinking, tools, mode, search).
  - Polling response dengan timeout + max iteration + deteksi error.
  - Stateless cleanup per request (clear cookies, close context, atau navigate temporary).

### Fase 5 — Model Cache System
- Pindahkan logika cache dari `client/client.py` ke `client/model_cache.py`.
- Background refresh setiap `MODEL_CACHE_TTL_MIN` (default 60), panggil `list_models()` tiap provider.
- Tulis `model.json` dengan format id `bridge/<provider>/<modality?>/<id>`.

### Fase 6 — Gateway Rebuild
- Buat `client/gateway.py` baru yang benar-benar OpenAI-compatible:
  - Parsing `model_id` konsisten.
  - SSE streaming valid: `finish_reason: "stop"` sebelum `[DONE]`.
  - Non-stream response dengan `created`, `id`, `usage` (estimasi).
  - Error taxonomy: 400, 401/424, 429, 502, 504.
  - Optional API key Bearer auth.
  - Graceful shutdown menutup browser/context.

### Fase 7 — CLI Client
- Buat `client/cli.py` (argparse + rich) yang memanggil gateway lokal/mesin lain via HTTP:
  - One-shot: `python -m client.cli chat -m bridge/qwen/qwen-max "Halo"`
  - REPL: `python -m client.cli chat -m bridge/deepseek/deepseek-v3 -i`
  - List models: `python -m client.cli models`
  - Extra params: `--param thinking=fast --param tools=true`
  - `--stream/--no-stream`, `--system "..."`.

### Fase 8 — Cleanup & Dokumentasi
- Pindahkan file root eksperimen ke `_legacy/` (kecuali `registry.py`, `providers/`, `README`, `how_to_use.md`, `model.md`, `requirements.txt`, `.env.example`).
- Tambah `.gitignore` untuk log/png/html/zip/sessions/browser_sessions.
- Update `README.md` dan `how_to_use.md` sinkron dengan implementasi final.

---

## 7. Pertanyaan Konfirmasi untuk User

Sebelum melanjutkan ke Fase 1, mohon konfirmasi hal-hal berikut:

1. **Server aktif**: Apakah benar yang berjalan adalah `server/server.js` di port 9877? Ataukah `bridge_server.py` di port 99876?
2. **Izinkan perbaikan server**: Bolehkah saya memperbaiki `server/server.js` (tambah `deepseek`, perbaiki `user_agent` qwen, dll.)? Atau client-only?
3. **Scope cleanup root**: Bolehkah file prototipe root (`engine.py`, `gateway.py`, `bridge_server.py`, `arena_cli.py`, `discovery_*.py`, `dom_probe.py`, `dump_text.py`, `count_models.py`, `test_all_models.py`, `bootstrap_cache.py`, zip, log, png, html) dipindah ke `_legacy/` dan dihapus dari tracking git?
4. **Kontrak provider**: Apakah setuju mengubah `BaseProvider` dari `execute(model_id, prompt, params) -> str` menjadi `chat_stream(model_id, messages, extra_params) -> AsyncIterator[str]`? Ini memungkinkan streaming real-time dan full history.
5. **Concurrency**: Preferensi desain concurrency — (a) satu browser context per request (paling sederhana, aman, tapi lebih lambat), atau (b) pool context dengan semaphore limit (lebih cepat, tapi perlu hati-hati state)?
6. **Auth**: Apakah ingin `API_KEY` Bearer auth wajib untuk semua endpoint `/v1/*`, atau opsional saja (hanya jika `.env` di-set)?

Jika user setuju, saya akan mulai rebuild dari Fase 1.
