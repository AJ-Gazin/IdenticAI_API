```markdown
# Flux Image Generation API Deployment Guide

## AWS EC2 Deployment Requirements
- **Instance Type**: g4dn.xlarge or better (NVIDIA T4 GPU)
- **AMI**: Ubuntu Server 22.04 LTS
- **Storage**: 150GB+ GP2 Volume
- **Security Group Ports**:
  - 8000 (FastAPI)
  - 8188 (ComfyUI internal)
  - 8888 (Monitoring - optional)
  - 22 (SSH - temporary)

## Installation Procedure
```bash
# Clone repository
git clone https://github.com/yourorg/flux-api.git && cd flux-api

# Configure environment
cp .env.example .env
nano .env  # Set required values

# Build container
docker-compose up -d --build

# Verify services
docker-compose logs -f flux-api
```

## Critical Environment Variables (.env)
```ini
HF_TOKEN="your_huggingface_token"           # Required for model downloads [3][4]
AWS_ACCESS_KEY_ID="your_aws_key"            # Required for future S3 integration [6]
AWS_SECRET_ACCESS_KEY="your_aws_secret"     # Required for future S3 integration [6]
MODEL_CACHE="/workspace/models"             # Persistent model storage [2]
```

## API Reference
### Generate Image (POST /generate)
```bash
curl -X POST "http://<EC2_IP>:8000/generate" \
-H "Content-Type: application/json" \
-d '{
    "prompt": "cyberpunk cat with neon glasses",
    "model_type": "dev",
    "width": 1024,
    "height": 1024,
    "lora_name": "steampunk.safetensors"
}'
```

### Expected Response
```json
{
    "status": "success",
    "image_url": "/output/flux_9a8b7c6d.png",
    "request_id": "9a8b7c6d-1234-5678-90ef-132435465768"
}
```

## Key File Structure
```
├── docker-compose.yml         # Production deployment config [6]
├── Dockerfile                 # CUDA 12.4 + Python 3.10 base [7]
├── scripts/
│   ├── download_models.sh     # Core model downloader [3]
│   └── download_loras.sh      # LoRA model installer [4]
└── api/
    ├── main.py                # FastAPI endpoints [1]
    └── flux_api.py            # Generation logic [0][10]
```

## Diagnostics & Troubleshooting
```bash
# Check GPU accessibility
docker exec flux-api nvidia-smi

# Force model re-download:
docker exec flux-api bash /scripts/download_models.sh

# View API logs:
docker-compose logs -f flux-api

# Verify ComfyUI connectivity:
curl http://localhost:8188

# Clean failed builds:
docker-compose down -v && docker system prune -a
```

## Security Requirements
**Immediate Actions Post-Deployment**:
```bash
1. Configure HTTPS reverse proxy (NGINX/Traefik)
2. Implement JWT authentication middleware [1][8]
3. Restrict security group to client IP ranges
4. Rotate HF_TOKEN/AWS keys weekly
5. Set filesystem permissions:
   chmod 750 /workspace/output
   chown www-data:docker /workspace/models
```

## Backup Strategy
```bash
# 1. Daily EBS snapshots
aws ec2 create-snapshot --volume-id vol-abc123

# 2. S3 sync for outputs
aws s3 sync /workspace/output s3://your-bucket/outputs

# 3. Model repository backup
tar -czvf models-$(date +%F).tar.gz /workspace/ComfyUI/models
```

## Monitoring Endpoints
```bash
GET /status          # Service health check [1]
GET /metrics         # Prometheus metrics (TODO)
GET /models/loras    # Available LoRAs [4]
```
