from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field
from typing import Optional, Dict, Any, List
from flux_api import FluxAPI, FluxAPIError, FluxErrorCode
import logging
import uuid
import os
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

# Initialize FastAPI
app = FastAPI(
    title="Flux Image Generation API",
    description="REST API for Text-to-Image Generation using ComfyUI",
    version="2.1.0",
    docs_url="/docs",
    redoc_url=None,
    openapi_url="/openapi.json"
)

# Add security middleware
app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=["*"]  # Configure as needed for production
)

# Mount static files directory for serving generated images
app.mount("/output", StaticFiles(directory="/output"), name="output")

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger("API")

from fastapi import FastAPI, HTTPException
from pydantic import BaseModel, Field, validator
from typing import Optional, List, Dict, Any
from enum import Enum

# --- Request Models ---
class ModelType(str, Enum):
    DEV = "dev"
    SCHNELL = "schnell"

class GenerationRequest(BaseModel):
    prompt: str = Field(
        ..., 
        description="Text prompt for image generation",
        min_length=1,
        max_length=500
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
        description="Negative prompt for improved results",
        max_length=500
    )
    width: int = Field(
        default=1024,
        description="Output image width",
        ge=64,
        le=2048
    )
    height: int = Field(
        default=1024,
        description="Output image height",
        ge=64,
        le=2048
    )

    @validator('width', 'height')
    def validate_dimensions(cls, v):
        if v % 8 != 0:
            raise ValueError("Dimensions must be multiples of 8")
        return v

# --- Response Models ---
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
    max_requests: int = Field(
        ..., 
        description="Maximum requests allowed in the time window",
        ge=0  # Changed from gt=0 to ge=0
    )
    time_window: int = Field(
        ..., 
        description="Time window in seconds",
        ge=0  # Changed from gt=0 to ge=0
    )
    remaining_tokens: float = Field(
        ..., 
        description="Number of remaining requests allowed",
        ge=0
    )

class SystemStatusResponse(BaseModel):
    status: str = Field(
        ..., 
        description="Overall system status (healthy/unhealthy/degraded)"
    )
    comfyui_available: bool = Field(
        ..., 
        description="Whether ComfyUI service is responding"
    )
    active_workers: int = Field(
        ..., 
        description="Number of active processing workers",
        ge=0
    )
    gpu_available: bool = Field(
        ..., 
        description="Whether GPU is available"
    )
    loras_available: int = Field(
        ..., 
        description="Number of available LoRA models",
        ge=0
    )
    rate_limit: RateLimitInfo = Field(
        ..., 
        description="Rate limiting information"
    )
class LoraListResponse(BaseModel):
    loras: List[str] = Field(
        ..., 
        description="List of available LoRA files"
    )
    default_lora: str = Field(
        ..., 
        description="Name of the default LoRA"
    )

# --- Example Responses ---
EXAMPLE_RESPONSES = {
    "generation_success": {
        "status": "success",
        "image_url": "/output/generated_123.png",
        "request_id": "550e8400-e29b-41d4-a716-446655440000"
    },
    "generation_error": {
        "status": "error",
        "request_id": "550e8400-e29b-41d4-a716-446655440000",
        "error": {
            "error": "GENERATION_FAILED",
            "message": "Failed to generate image",
            "request_id": "550e8400-e29b-41d4-a716-446655440000"
        }
    },
    "system_status": {
        "status": "healthy",
        "comfyui_available": True,
        "active_workers": 1,
        "gpu_available": True,
        "loras_available": 2,
        "rate_limit": {
            "max_requests": 10,
            "time_window": 60,
            "remaining_tokens": 8.5
        }
    },
    "lora_list": {
        "loras": ["steampunk.safetensors", "cyberpunk.safetensors"],
        "default_lora": "steampunk.safetensors"
    }
}
# --- Error Handling ---
@app.exception_handler(FluxAPIError)
async def flux_error_handler(request, exc: FluxAPIError):
    """Handle FluxAPI specific errors"""
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
    """Handle unexpected errors"""
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
@app.post(
    "/generate",
    response_model=GenerationResponse,
    summary="Generate Image",
    description="Process text prompt into generated image using specified model parameters"
)
async def generate_image(request: GenerationRequest):
    """Main endpoint for image generation"""
    request_id = str(uuid.uuid4())
    logger.info(f"[{request_id}] Starting generation request with prompt: {request.prompt[:50]}...")
    
    try:
        # Initialize API
        flux = FluxAPI()
        
        # Execute generation
        filename = flux.generate_image(
            prompt=request.prompt,
            lora_name=request.lora_name,
            model_type=request.model_type,
            seed=request.seed,
            negative_prompt=request.negative_prompt,
            width=request.width,
            height=request.height
        )
        
        logger.info(f"[{request_id}] Generation completed successfully, file: {filename}")
        
        # Return success response
        return GenerationResponse(
            status="success",
            image_url=f"/output/{os.path.basename(filename)}",
            request_id=request_id
        )
        
    except FluxAPIError as e:
        error_detail = ErrorDetail(
            error=e.error_code.value,
            message=e.message,
            request_id=request_id
        )
        return GenerationResponse(
            status="error",
            request_id=request_id,
            error=error_detail
        )
    except Exception as e:
        error_detail = ErrorDetail(
            error="INTERNAL_ERROR",
            message=str(e),
            request_id=request_id
        )
        return GenerationResponse(
            status="error",
            request_id=request_id,
            error=error_detail
        )

@app.get(
    "/status",
    response_model=SystemStatusResponse,
    tags=["system"],
    summary="System Health Check",
    description="Get current service status and component availability"
)
async def get_status():
    """System health check endpoint"""
    try:
        flux = FluxAPI()
        status_info = flux.get_system_info()
        
        # Ensure rate limit info has valid values
        if status_info['status'] == 'degraded':
            status_info['rate_limit'] = {
                'max_requests': 1,  # Use minimum valid values instead of 0
                'time_window': 1,
                'remaining_tokens': 0.0
            }
            
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
                max_requests=1,  # Use minimum valid values instead of 0
                time_window=1,
                remaining_tokens=0.0
            )
        )

@app.get(
    "/models/loras",
    response_model=LoraListResponse,
    tags=["models"],
    summary="List Available LoRAs",
    description="Retrieve list of available LoRA adapters"
)
async def list_available_loras():
    """List available LoRA models"""
    try:
        flux = FluxAPI()
        loras = flux.list_available_loras()
        return LoraListResponse(
            loras=loras,
            default_lora="steampunk.safetensors"
        )
    except Exception as e:
        logger.error(f"Failed to list LoRAs: {str(e)}")
        raise HTTPException(
            status_code=500,
            detail={"error": "INTERNAL_ERROR", "message": str(e)}
        )

# --- Startup Event ---
@app.on_event("startup")
async def startup_event():
    """Initialize API on startup"""
    logger.info("API starting up...")
    try:
        # Verify output directory exists and is writable
        os.makedirs("/output", exist_ok=True)
        if not os.access("/output", os.W_OK):
            logger.error("Output directory is not writable!")
            raise Exception("Output directory /output is not writable")
            
        # Test ComfyUI connection
        flux = FluxAPI()
        if not flux.check_comfy_status():
            logger.error("ComfyUI service is not available!")
            raise Exception("ComfyUI service is not available")
            
        logger.info("API startup completed successfully")
    except Exception as e:
        logger.error(f"API startup failed: {str(e)}")
        raise