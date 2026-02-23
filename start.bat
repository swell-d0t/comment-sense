@echo off
REM ─────────────────────────────────────────────────────────────────────────
REM  CommentSense — Windows Backend Startup
REM  Run this from the comment-sense\backend directory
REM ─────────────────────────────────────────────────────────────────────────

REM Step 1: Create virtual environment (only needed once)
IF NOT EXIST "venv" (
    echo Creating virtual environment...
    python -m venv venv
)

REM Step 2: Activate
call venv\Scripts\activate.bat

REM Step 3: Install dependencies (only needed once or after requirements change)
pip install -r requirements.txt

REM Step 4: Copy .env.example to .env if it doesn't exist yet
IF NOT EXIST ".env" (
    echo No .env file found. Copying .env.example to .env...
    copy .env.example .env
    echo IMPORTANT: Open .env and fill in your META_APP_ID, META_APP_SECRET,
    echo ENCRYPTION_KEY, JWT_SECRET, and DATABASE_URL before starting.
    pause
)

REM Step 5: Start the server
echo Starting CommentSense API on http://localhost:8000
echo API docs available at http://localhost:8000/docs
uvicorn main:app --reload --host 0.0.0.0 --port 8000
