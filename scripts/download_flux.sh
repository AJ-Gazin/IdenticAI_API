#!/bin/bash
echo "using hf_transfer for faster downloads"

pip install huggingface-hub[hf_transfer]
pip install hf_transfer
export HF_HUB_ENABLE_HF_TRANSFER=1

echo "Downloading FLUX.dev-fp8"
cd /ComfyUI/models/diffusion_models/
timeout 300 huggingface-cli download kijai/flux-fp8 flux1-dev-fp8.safetensors --local-dir ./ || echo "Flux FP8 Download Failed (5min) - check ~/.cache/huggingface/download/"

echo "Download FLUX.schnell"
cd /ComfyUI/models/diffusion_models/
timeout 300 huggingface-cli download black-forest-labs/FLUX.1-schnell flux1-schnell.safetensors --local-dir ./ || echo "Flux Schnell Download Failed (5min) - check ~/.cache/huggingface/download/"


echo "Downloading FLUX VAE" 
cd /ComfyUI/models/vae/
timeout 120 huggingface-cli download kijai/flux-fp8 flux-vae-bf16.safetensors --local-dir ./ || echo "flux-vae-bf16 Download Failed"

echo "Downloading Text Encoders"
cd /ComfyUI/models/clip/
echo "Downloading clip_l"
timeout 120 huggingface-cli download comfyanonymous/flux_text_encoders clip_l.safetensors --local-dir ./ || echo "clip_l Download Failed"

echo "Download t5xxl_fp16"
timeout 300 huggingface-cli download comfyanonymous/flux_text_encoders t5xxl_fp16.safetensors --local-dir ./ || echo "t5xxl_fp16 Download Failed"
