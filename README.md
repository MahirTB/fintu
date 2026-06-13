# fintu

A fast, lightweight personal finance tracker built to load instantly and look clean. No heavy frontend frameworks, tracking libraries, or ads.

It runs on **FastAPI** for the backend, **HTMX** for single-page reactive DOM swaps, and raw **Vanilla CSS** for the interface.

---

## Core Features

*   **Responsive Segmented Filters:** Horizontal overflow-x scrolling on mobile viewports to prevent layout wrapping on filter pills.
*   **Tactile Category Indicators:** Color-coded border-left cues (income vs expense) for instant transaction scanning.
*   **Interactive 60-Day Calendar:** Custom monthly grid mapping activity logs with automated viewport scroll-to-breakdown target transitions.
*   **SQLite & PostgreSQL Compatibility:** Auto-detects and switches database engines dynamically based on the environment `DATABASE_URL` string (e.g. Supabase, Neon).

---

## Quick Start

### 1. Set Up
```bash
git clone https://github.com/MahirTB/fintu.git
cd fintu
python -m venv .venv
```

### 2. Activate & Install
*   **Windows:** `.venv\Scripts\Activate.ps1`
*   **Mac/Linux:** `source .venv/bin/activate`

```bash
pip install -r requirements.txt
```

### 3. Run Development Server
```bash
uvicorn main:app --reload
```
Open `http://127.0.0.1:8000`. The local SQLite database (`finance.db`) will initialize itself on the first connection.

---

## Free Cloud Deployment

*   **Render + Supabase:** Deploy the web service on **Render** (Free Web Service) and set `DATABASE_URL` pointing to your free **Supabase** Postgres instance.
*   **Fly.io:** Spin up a free VM on **Fly.io** and mount a free 1GB persistent volume to `/data` to store the local SQLite database.

---

## License
Licensed under the [MIT License](LICENSE).
