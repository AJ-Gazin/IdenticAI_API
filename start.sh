#!/bin/bash

# --- Functions ---
init_comfyui_dirs() {
    echo "Configuring ComfyUI directories..."
    
    # Clean existing symlink if present
    if [ -L "/ComfyUI" ]; then
        echo "Removing existing ComfyUI symlink"
        rm -f /ComfyUI
    fi
    
    # Initialize physical directories
    mkdir -p /workspace/ComfyUI/output
    chmod 755 /workspace/ComfyUI/output
    
    # Create system symlink
    echo "Creating /ComfyUI symlink"
    ln -s /workspace/ComfyUI /ComfyUI
}

wait_for_comfyui() {
    echo "Waiting for ComfyUI to be ready..."
    max_attempts=30
    attempt=1
    
    while [ $attempt -le $max_attempts ]; do
        if curl -s --fail "http://127.0.0.1:8188/history" >/dev/null; then
            echo "ComfyUI startup confirmed"
            return 0
        fi
        echo "ComfyUI check attempt $attempt/$max_attempts"
        sleep 2
        attempt=$((attempt + 1))
    done
    
    echo "ComfyUI failed to initialize within timeout" >&2
    return 1
}

# --- Initialization Phase ---
echo "Starting container initialization..."
mkdir -p /workspace
init_comfyui_dirs

# Set permissions for runtime user
echo "Setting directory permissions..."
chown -R 1000:1000 /workspace /ComfyUI
chmod 755 /workspace /ComfyUI

# --- ComfyUI Workspace Setup ---
echo "Configuring ComfyUI workspace..."
sed -i 's/mv --no-clobber \/ComfyUI/# Disabled directory move/g' ./scripts/comfyui-on-workspace.sh
sed -i 's/rm -rf \/ComfyUI/# Disabled directory removal/g' ./scripts/comfyui-on-workspace.sh
./scripts/comfyui-on-workspace.sh

# --- Model Downloads ---
echo "Starting model downloads..."
find ./scripts/ -name "*.sh" -exec dos2unix {} +  # Force line ending conversion
bash ./scripts/download_flux.sh
bash ./scripts/download_flux_loras.sh

# --- HuggingFace Authentication ---
if [ -n "$HF_TOKEN" ] && [ "$HF_TOKEN" != "enter_your_huggingface_token_here" ]; then
    echo "Authenticating with HuggingFace..."
    huggingface-cli login --token "$HF_TOKEN" <<< "y"
fi

# --- Runtime Service Launch ---
echo "Starting ComfyUI..."
python3 /workspace/ComfyUI/main.py \
    --listen 0.0.0.0 \
    --port 8188 \
    --output-directory /ComfyUI/output &

# Wait for core service initialization
if ! wait_for_comfyui; then
    exit 1
fi

echo "Starting API server..."
export PYTHONPATH="/api:${PYTHONPATH}"
uvicorn api.main:app \
    --host 0.0.0.0 \
    --port 8000 \
    --log-level warning &

# --- Process Management ---
echo "All services operational"
trap 'echo "Shutdown signal received"; kill 0' SIGINT SIGTERM
wait
