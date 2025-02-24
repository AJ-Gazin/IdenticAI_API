from fastapi import FastAPI, HTTPException
from pydantic import (
    BaseModel, 
    Field, 
    field_validator,
    ValidationInfo
)
from typing import Optional, Dict, Any, List
from flux_api import FluxAPI, FluxAPIError, FluxErrorCode
import logging
import uuid
import os
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from fastapi.middleware.cors import CORSMiddleware
from enum import Enum

app = FastAPI(
    title="Flux Image Generation API",
    description="REST API for Text-to-Image Generation using ComfyUI",
    version="2.1.0",
    docs_url="/docs",
    redoc_url=None,
    openapi_url="/openapi.json"
)

# CORS and middleware setup
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.add_middleware(TrustedHostMiddleware, allowed_hosts=["*"])
app.mount("/output", StaticFiles(directory="/ComfyUI/output"), name="output")

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("API")

# --- Data Models ---
class ModelType(str, Enum):
    DEV = "dev"
    SCHNELL = "schnell"

class GenerationRequest(BaseModel):
    prompt: str = Field(
        ..., 
        min_length=1,
        max_length=500,
        description="Text prompt for image generation"
    )
    lora_name: Optional[str] = Field(
        default="steampunk.safetensors",
        description="Name of the LoRA model to use"
    )
    model_type: ModelType = Field(
        default=ModelType.DEV,
        description="Model type to use (dev or schnell)"
    )
    seed: Optional[int] = Field(
        default=None,
        description="Seed for reproducible generation"
    )
    negative_prompt: Optional[str] = Field(
        default=None,
        max_length=500,
        description="Negative prompt for improved results"
    )
    width: int = Field(
        default=1024,
        ge=64,
        le=2048,
        description="Output image width",
        validate_default=True
    )
    height: int = Field(
        default=1024,
        ge=64,
        le=2048,
        description="Output image height",
        validate_default=True
    )

    @field_validator('width', 'height', mode='before')
    @classmethod
    def validate_dimensions(cls, value: int, info: ValidationInfo) -> int:
        if value % 8 != 0:
            raise ValueError(f"{info.field_name} must be multiple of 8")
        return value

class ErrorDetail(BaseModel):
    error: str = Field(..., description="Error code")
    message: str = Field(..., description="Error message")
    request_id: str = Field(..., description="Request ID for tracking")

class GenerationResponse(BaseModel):
    status: str = Field(..., description="Status of the request (success/error)")
    image_url: Optional[str] = Field(None, description="URL path to the generated image")
    request_id: str = Field(..., description="Unique identifier for the request")
    error: Optional[ErrorDetail] = Field(None, description="Error details if generation failed")

class RateLimitInfo(BaseModel):
    max_requests: int = Field(..., ge=0, description="Maximum requests allowed")
    time_window: int = Field(..., ge=0, description="Time window in seconds")
    remaining_tokens: float = Field(..., ge=0, description="Remaining requests")

class SystemStatusResponse(BaseModel):
    status: str = Field(..., description="System status")
    comfyui_available: bool = Field(..., description="ComfyUI availability")
    active_workers: int = Field(..., ge=0, description="Active workers")
    gpu_available: bool = Field(..., description="GPU status")
    loras_available: int = Field(..., ge=0, description="Available LoRAs")
    rate_limit: RateLimitInfo = Field(..., description="Rate limiting info")

class LoraListResponse(BaseModel):
    loras: List[str] = Field(..., description="Available LoRA files")
    default_lora: str = Field(..., description="Default LoRA")

# --- Error Handlers ---
@app.exception_handler(FluxAPIError)
async def flux_error_handler(request, exc: FluxAPIError):
    return JSONResponse(
        status_code=400,
        content={
            "status": "error",
            "error": exc.error_code.value,
            "message": exc.message,
            "request_id": getattr(request.state, "request_id", None)
        }
    )

@app.exception_handler(Exception)
async def general_exception_handler(request, exc: Exception):
    logger.exception("Unexpected error occurred")
    return JSONResponse(
        status_code=500,
        content={
            "status": "error",
            "error": "INTERNAL_ERROR",
            "message": str(exc),
            "request_id": getattr(request.state, "request_id", None)
        }
    )

# --- API Endpoints ---
@app.post("/generate", response_model=GenerationResponse)
async def generate_image(request: GenerationRequest):
    request_id = str(uuid.uuid4())
    logger.info(f"[{request_id}] Starting generation request")
    
    try:
        flux = FluxAPI()
        filename = flux.generate_image(
            prompt=request.prompt,
            lora_name=request.lora_name,
            model_type=request.model_type,
            seed=request.seed,
            negative_prompt=request.negative_prompt,
            width=request.width,
            height=request.height
        )
        
        return GenerationResponse(
            status="success",
            image_url=f"/output/{os.path.basename(filename)}",
            request_id=request_id
        )
        
    except FluxAPIError as e:
        return GenerationResponse(
            status="error",
            request_id=request_id,
            error=ErrorDetail(
                error=e.error_code.value,
                message=e.message,
                request_id=request_id
            )
        )
    except Exception as e:
        return GenerationResponse(
            status="error",
            request_id=request_id,
            error=ErrorDetail(
                error="INTERNAL_ERROR",
                message=str(e),
                request_id=request_id
            )
        )

@app.get("/status", response_model=SystemStatusResponse)
async def get_status():
    try:
        flux = FluxAPI()
        status_info = flux.get_system_info()
        return SystemStatusResponse(**status_info)
    except Exception as e:
        logger.error(f"Status check failed: {str(e)}")
        return SystemStatusResponse(
            status="degraded",
            comfyui_available=False,
            active_workers=0,
            gpu_available=False,
            loras_available=0,
            rate_limit=RateLimitInfo(
                max_requests=1,
                time_window=1,
                remaining_tokens=0.0
            )
        )

@app.get("/models/loras", response_model=LoraListResponse)
async def list_available_loras():
    try:
        flux = FluxAPI()
        return LoraListResponse(
            loras=flux.list_available_loras(),
            default_lora="steampunk.safetensors"
        )
    except Exception as e:
        logger.error(f"Failed to list LoRAs: {str(e)}")
        raise HTTPException(500, detail={"error": "INTERNAL_ERROR", "message": str(e)})

# --- Startup Validation ---
@app.on_event("startup")
async def startup_event():
    logger.info("API starting up...")
    try:
        os.makedirs("/ComfyUI/output", exist_ok=True)
        if not os.access("/ComfyUI/output", os.W_OK):
            raise PermissionError("Output directory not writable")
            
        flux = FluxAPI()
        if not flux.check_comfy_status():
            raise ConnectionError("ComfyUI unavailable")
            
        logger.info("API startup completed")
    except Exception as e:
        logger.error(f"Startup failed: {str(e)}")
        raise
