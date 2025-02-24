#!/bin/bash

# --- Functions ---
wait_for_comfyui() {
    echo "Waiting for ComfyUI to be ready..."
    max_attempts=30
    attempt=1
    
    while [ $attempt -le $max_attempts ]; do
        if curl -s "http://127.0.0.1:8188/history" > /dev/null; then
            echo "ComfyUI is ready!"
            return 0
        fi
        echo "Attempt $attempt/$max_attempts - ComfyUI not ready yet..."
        sleep 2
        attempt=$((attempt + 1))
    done
    
    echo "ComfyUI failed to start after $max_attempts attempts"
    return 1
}

# --- Setup ---
echo "Setting up workspace..."
mkdir -p /workspace /output
chmod 777 /output  # Ensure directory is writable

# --- Initialize ComfyUI ---
./scripts/comfyui-on-workspace.sh

# --- Download Models ---
echo "Downloading models..."
./scripts/download_flux.sh
./scripts/download_flux_loras.sh

# --- HuggingFace Login ---
if [[ $HF_TOKEN && $HF_TOKEN != "enter_your_huggingface_token_here" ]]; then
    echo "Logging into HuggingFace..."
    huggingface-cli login --token $HF_TOKEN
fi

# --- Start Services ---
echo "Starting services..."

# Start ComfyUI in background
echo "Starting ComfyUI..."
python3 /workspace/ComfyUI/main.py --listen 0.0.0.0 --port 8188 &

# Wait for ComfyUI to be available
if ! wait_for_comfyui; then
    echo "Failed to start ComfyUI - exiting"
    exit 1
fi

# Start FastAPI
echo "Starting FastAPI..."
export PYTHONPATH="${PYTHONPATH}:/api"
uvicorn api.main:app --host 0.0.0.0 --port 8000 &

# Keep container running and handle signals properly
trap "kill 0" SIGINT SIGTERM
wait