#!/bin/bash
cd /home/vladni/Projects/job-hunter-ai
source venv/bin/activate

# Load environment variables from .env or .env.local
if [ -f .env.local ]; then
    set -a; source .env.local; set +a
elif [ -f .env ]; then
    set -a; source .env; set +a
fi

exec uvicorn main:app --host 0.0.0.0 --port 3002