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

# Resolve ComfyUI main path across base image variants.
COMFY_MAIN=""
if [ -f "/ComfyUI/main.py" ]; then
    COMFY_MAIN="/ComfyUI/main.py"
elif [ -f "/workspace/runpod-slim/ComfyUI/main.py" ]; then
    COMFY_MAIN="/workspace/runpod-slim/ComfyUI/main.py"
else
    echo "Error: ComfyUI main.py not found"
    exit 1
fi

echo "Using ComfyUI entrypoint: ${COMFY_MAIN}"

# Resolve handler path.
HANDLER_MAIN=""
if [ -f "/handler.py" ]; then
    HANDLER_MAIN="/handler.py"
elif [ -f "/workspace/handler.py" ]; then
    HANDLER_MAIN="/workspace/handler.py"
else
    echo "Error: handler.py not found"
    exit 1
fi

# Enable sage attention only when explicitly requested and available.
# Set USE_SAGE_ATTENTION=true to request it.
COMFY_EXTRA_ARGS=()
if [ "${USE_SAGE_ATTENTION:-false}" = "true" ]; then
    if "${PYTHON_BIN}" -c "import sageattention" >/dev/null 2>&1; then
        COMFY_EXTRA_ARGS+=("--use-sage-attention")
        echo "Sage attention enabled"
    else
        echo "Warning: USE_SAGE_ATTENTION=true but sageattention is not installed. Starting without --use-sage-attention."
    fi
fi

# Start ComfyUI in the background
echo "Starting ComfyUI in the background..."
"${PYTHON_BIN}" "${COMFY_MAIN}" --listen 0.0.0.0 --port 8188 "${COMFY_EXTRA_ARGS[@]}" &
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
exec "${PYTHON_BIN}" -u "${HANDLER_MAIN}"