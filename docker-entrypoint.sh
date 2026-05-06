#!/usr/bin/env bash
set -e

echo "Starting TradeClaw..."

# Start the FastAPI backend in the background
echo "Starting backend..."
cd /app/backend
# Since we installed globally in the container, no venv needed
python3 -m uvicorn main:app --host 0.0.0.0 --port 8000 &
BACKEND_PID=$!

# Start the Next.js standalone frontend
echo "Starting frontend..."
cd /app/frontend
HOSTNAME="0.0.0.0" PORT=3000 node server.js &
FRONTEND_PID=$!

# Define cleanup function
cleanup() {
    echo "Stopping TradeClaw..."
    kill -TERM $BACKEND_PID
    kill -TERM $FRONTEND_PID
    wait $BACKEND_PID
    wait $FRONTEND_PID
}

# Trap termination signals
trap cleanup SIGTERM SIGINT

# Wait for any process to exit
wait -n

echo "A process exited unexpectedly."
cleanup
exit 1
