#!/bin/bash

# Ensure workspace directory exists
mkdir -p /workspace

# Move or cleanup logic
if [[ ! -d /workspace/ComfyUI ]]; then
    echo "Initializing new ComfyUI workspace"
    mv -v /ComfyUI /workspace 2>/dev/null || echo "Move skipped: source/dest conflict"
else
    echo "Cleaning default ComfyUI location"
    rm -rfv /ComfyUI 2>/dev/null || :
fi

# Create system symlink
echo "Creating directory symlink"
ln -svf /workspace/ComfyUI /ComfyUI
