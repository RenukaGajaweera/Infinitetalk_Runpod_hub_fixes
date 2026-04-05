#!/bin/bash

# Exit immediately if a command exits with a non-zero status.
set -euo pipefail

# Resolve python executable across different base images.
PYTHON_BIN=""
if command -v python >/dev/null 2>&1; then
    PYTHON_BIN="python"
elif command -v python3 >/dev/null 2>&1; then
    PYTHON_BIN="python3"
elif [ -x "/workspace/runpod-slim/ComfyUI/.venv-cu128/bin/python" ]; then
    PYTHON_BIN="/workspace/runpod-slim/ComfyUI/.venv-cu128/bin/python"
elif [ -x "/ComfyUI/.venv-cu128/bin/python" ]; then
    PYTHON_BIN="/ComfyUI/.venv-cu128/bin/python"
else
    echo "Error: No usable python executable found"
    exit 1
fi

echo "Using python executable: ${PYTHON_BIN}"

# Start ComfyUI in the background
echo "Starting ComfyUI in the background..."
"${PYTHON_BIN}" /ComfyUI/main.py --listen 0.0.0.0 --port 8188 --use-sage-attention &
COMFY_PID=$!

# Wait for ComfyUI to be ready
echo "Waiting for ComfyUI to be ready..."
max_wait=120  # 최대 2분 대기
wait_count=0
while [ $wait_count -lt $max_wait ]; do
    if ! kill -0 "$COMFY_PID" >/dev/null 2>&1; then
        echo "Error: ComfyUI process exited before becoming ready"
        exit 1
    fi

    if curl -s http://127.0.0.1:8188/ > /dev/null 2>&1; then
        echo "ComfyUI is ready!"
        break
    fi
    echo "Waiting for ComfyUI... ($wait_count/$max_wait)"
    sleep 2
    wait_count=$((wait_count + 2))
done

if [ $wait_count -ge $max_wait ]; then
    echo "Error: ComfyUI failed to start within $max_wait seconds"
    exit 1
fi

# Start the handler in the foreground
# 이 스크립트가 컨테이너의 메인 프로세스가 됩니다.
echo "Starting the RunPod handler worker..."
exec "${PYTHON_BIN}" -u /handler.py