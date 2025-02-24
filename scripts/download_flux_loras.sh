#!/bin/bash

download_lora() {
    local repo=$1
    local filename=$2
    local final_name=$3
    
    echo "Downloading LORA - ${final_name}"
    cd /ComfyUI/models/loras/
    
    # Remove existing file if it exists
    rm -f "${final_name}.safetensors"
    
    # Download and move in one operation, with timeout
    timeout 300 bash -c "huggingface-cli download ${repo} ${filename} --local-dir ./ && mv -f ${filename} ${final_name}.safetensors" || echo "Lora Download Failed (5min) - check ~/.cache/huggingface/download/"
}

# Download steampunk LoRA
download_lora "sohvren/steampunkanimals" "steampunkanimals.safetensors" "steampunk"