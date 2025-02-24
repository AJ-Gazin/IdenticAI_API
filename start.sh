#!/bin/bash

# --- Functions ---
wait_for_comfyui() {
    echo "Waiting for ComfyUI to be ready..."
    max_attempts=30
    attempt=1
    
    while [ $attempt -le $max_attempts ]; do
        return_code=0
        curl -s "http://127.0.0.1:8188/history" > /dev/null || return_code=$?
        
        if [ $return_code -eq 0 ]; then
            echo "ComfyUI version $(curl -s http://127.0.0.1:8188/sdapi/v1/version | jq .version) is ready!"
            return 0
        fi
        
        echo "Attempt $attempt/$max_attempts - ComfyUI not ready yet..."
        sleep 2
        attempt=$((attempt + 1))
    done
    
    echo "ComfyUI failed to start after $max_attempts attempts" >&2
    return 1
}

# --- Setup ---
echo "Setting up workspace and output directories..."
mkdir -p /workspace /output
chown -R 1000:1000 /workspace /output
chmod 755 /workspace /output
logger "Created workspace and output directories with permissions 755"

# --- Initialize ComfyUI ---
echo "Initializing ComfyUI workspace..."
./scripts/comfyui-on-workspace.sh

# --- Download Models ---
echo "Downloading base models..."
./scripts/download_flux.sh
echo "Downloading LoRA models..."
./scripts/download_flux_loras.sh

# --- HuggingFace Login ---
if [[ $HF_TOKEN && $HF_TOKEN != "enter_your_huggingface_token_here" ]]; then
    echo "Logging into HuggingFace..."
    huggingface-cli login --token $HF_TOKEN --add-to-git-credential
fi

# --- Start Services ---
echo "Starting ComfyUI..."
python3 /workspace/ComfyUI/main.py \
    --listen 0.0.0.0 \
    --port 8188 \
    --output-directory /output &

# Wait for ComfyUI initialization
if ! wait_for_comfyui; then
    exit 1
fi

echo "Starting FastAPI..."
export PYTHONPATH="${PYTHONPATH}:/api"
uvicorn api.main:app \
    --host 0.0.0.0 \
    --port 8000 \
    --log-level info &

# --- Process Management ---
echo "All services started. Monitoring processes..."
trap "echo 'Shutting down...'; kill -TERM 0" SIGINT SIGTERM
wait
