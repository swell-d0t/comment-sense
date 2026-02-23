# CommentSense — Complete Setup Guide (Windows)

## Prerequisites

Install these before anything else:

1. **Python 3.11+** — https://python.org/downloads
   - During install, check "Add Python to PATH"
   - Verify: open Command Prompt, type `python --version`

2. **Node.js 20+** — https://nodejs.org
   - Download the LTS version
   - Verify: `node --version`

3. **PostgreSQL 16** — https://www.postgresql.org/download/windows/
   - During install, set a password for the `postgres` user — write it down
   - Default port 5432 is fine
   - After install, open pgAdmin or psql and run:
     ```sql
     CREATE DATABASE commentsense;
     ```

4. **Redis for Windows** — https://github.com/microsoftarchive/redis/releases
   - Download Redis-x64-3.0.504.msi and install
   - It runs as a Windows service automatically
   - Verify: open a new Command Prompt, type `redis-cli ping` — should return PONG

5. **Git** — https://git-scm.com/download/win

---

## Backend Setup

Open Command Prompt (`Win + R`, type `cmd`, press Enter).

```
cd path\to\comment-sense\backend
```

Replace `path\to` with wherever you put the folder. For example:
```
cd C:\Users\YourName\Desktop\comment-sense\backend
```

Now run the startup script:
```
start.bat
```

The first time this runs it will:
- Create a Python virtual environment
- Install all dependencies (this takes a few minutes — PyTorch is large)
- Copy `.env.example` to `.env` and pause

**Fill in your `.env` file** before continuing. Open it in Notepad:

```
DATABASE_URL=postgresql+asyncpg://postgres:YOUR_PASSWORD@localhost:5432/commentsense
META_APP_ID=your_app_id_from_meta_developer_console
META_APP_SECRET=your_app_secret_from_meta_developer_console
REDIRECT_URI=http://localhost:8000/auth/callback
FRONTEND_URL=http://localhost:3000
ALLOWED_ORIGINS=http://localhost:3000
```

For `ENCRYPTION_KEY` and `JWT_SECRET`, generate them by running:
```
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
python -c "import secrets; print(secrets.token_hex(32))"
```
Paste those values into `.env`.

Once `.env` is filled in, run `start.bat` again. The server starts at:
- API: http://localhost:8000
- Docs: http://localhost:8000/docs

---

## Frontend Setup

Open a **second** Command Prompt window:

```
cd path\to\comment-sense\frontend
npm install
```

Create a `.env.local` file in the frontend folder:
```
NEXT_PUBLIC_API_URL=http://localhost:8000
```

Then start the dev server:
```
npm run dev
```

Frontend runs at http://localhost:3000.

---

## How to Use the App (Development Flow)

1. Start the backend (`start.bat` in one terminal)
2. Start the frontend (`npm run dev` in another terminal)
3. Open http://localhost:3000
4. Click "Continue with Instagram" — this will redirect to Instagram's login
5. After authorizing, you'll be redirected to /dashboard
6. Go to /analyze → "My Instagram Posts" to see your posts
7. Click a post → "Fetch & Analyze Comments" to run sentiment analysis
8. Or use the "Paste Comments" tab for manual paste-based analysis

---

## Running the Tests

```
cd path\to\comment-sense\backend
venv\Scripts\activate.bat
pytest tests\ -v -m "not integration"
```

The `not integration` flag skips tests that require the full 500MB RoBERTa model.
To run everything including real model inference:
```
pytest tests\ -v
```

---

## Project Structure

```
comment-sense/
├── backend/
│   ├── main.py                    ← FastAPI app entrypoint
│   ├── db.py                      ← Database connection
│   ├── start.bat                  ← Windows startup script
│   ├── requirements.txt
│   ├── .env.example               ← Copy to .env and fill in
│   ├── models/
│   │   └── db_models.py           ← SQLAlchemy ORM models
│   ├── routers/
│   │   ├── auth.py                ← Instagram OAuth flow
│   │   ├── analyze.py             ← Sentiment analysis endpoints
│   │   ├── instagram.py           ← Instagram API (posts + comments)
│   │   └── history.py             ← Saved analysis history
│   ├── services/
│   │   ├── parser.py              ← Instagram comment extraction
│   │   ├── hybrid.py              ← VADER + RoBERTa pipeline
│   │   └── token_store.py         ← Token encryption + refresh
│   └── tests/
│       ├── test_parser.py
│       ├── test_hybrid.py
│       ├── test_api.py
│       └── test_token_store.py
└── frontend/                      ← Next.js app (built with v0 + Cursor)
```
