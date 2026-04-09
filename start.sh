#!/bin/bash
cd /home/vladni/Projects/job-hunter-ai
source venv/bin/activate

# Add your Groq API key here (free tier works)
export GROQ_API_KEY="gsk_your_key_here"

exec uvicorn main:app --host 0.0.0.0 --port 3002