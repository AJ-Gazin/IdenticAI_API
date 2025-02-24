#!/usr/bin/env python3
"""
Flux API Core - ComfyUI Integration Layer
Provides programmatic access to ComfyUI workflows with enhanced controls
"""

import json
import urllib.request
import websocket
import os
import time
import uuid
import logging
import random
from enum import Enum
from typing import Optional, Dict, Any, List
from collections import deque

# --- Constants ---
DEFAULT_LORA = "steampunk.safetensors"
DEFAULT_OUTPUT_DIR = "/ComfyUI/output"
WORKFLOW_BASE_PATH = "/workflows"
MAX_RETRIES = 3
RETRY_DELAY = 5  # seconds

# --- Error Handling ---
class FluxErrorCode(Enum):
    LORA_NOT_FOUND = "LORA_NOT_FOUND"
    COMFY_UNAVAILABLE = "COMFY_UNAVAILABLE"
    WORKFLOW_ERROR = "WORKFLOW_ERROR"
    CONNECTION_ERROR = "CONNECTION_ERROR"
    GENERATION_FAILED = "GENERATION_FAILED"
    SAVE_ERROR = "SAVE_ERROR"
    RATE_LIMIT = "RATE_LIMIT"
    INVALID_INPUT = "INVALID_INPUT"

class FluxAPIError(Exception):
    """Custom API exception with structured error information"""
    def __init__(self, message: str, error_code: FluxErrorCode):
        self.message = message
        self.error_code = error_code
        super().__init__(f"{error_code.value}: {message}")

# --- Rate Limiting ---
class RateLimiter:
    """Token bucket rate limiter implementation"""
    def __init__(self, max_requests: int = 10, time_window: int = 60):
        self.max_requests = max_requests
        self.time_window = time_window
        self.tokens = max_requests
        self.last_refill = time.time()

    def _refill(self):
        now = time.time()
        elapsed = now - self.last_refill
        refill_amount = elapsed * (self.max_requests / self.time_window)
        
        if refill_amount > 1:
            self.tokens = min(
                self.tokens + refill_amount,
                self.max_requests
            )
            self.last_refill = now

    def is_allowed(self) -> bool:
        self._refill()
        if self.tokens >= 1:
            self.tokens -= 1
            return True
        return False

    def get_remaining_tokens(self) -> float:
        self._refill()
        return self.tokens

# --- Core API Class ---
class FluxAPI:
    def __init__(self, 
                 host: str = "127.0.0.1", 
                 port: str = "8188",
                 log_level: int = logging.INFO,
                 rate_limit: int = 10,
                 rate_window: int = 60):
        
        # Network configuration
        self.host = host
        self.port = port
        self.base_url = f"http://{self.host}:{self.port}"
        self.ws_url = f"ws://{self.host}:{self.port}/ws"
        
        # Path configuration
        self.workflow_paths = {
            'dev': f"{WORKFLOW_BASE_PATH}/flux-dev-workflow.json",
            'schnell': f"{WORKFLOW_BASE_PATH}/flux-schnell-workflow.json"
        }
        self.lora_dir = "/ComfyUI/models/loras"
        self.output_dir = DEFAULT_OUTPUT_DIR
        
        # System state
        self.active_connections = 0
        self.rate_limiter = RateLimiter(rate_limit, rate_window)
        
        # Logging setup
        self._setup_logging(log_level)
        self.logger.info("FluxAPI initialized")

    def _setup_logging(self, log_level: int) -> None:
        """Configure logging handlers and formats"""
        self.logger = logging.getLogger('FluxAPI')
        self.logger.setLevel(log_level)

        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )

        # Console handler
        ch = logging.StreamHandler()
        ch.setFormatter(formatter)
        self.logger.addHandler(ch)

        # File handler
        fh = logging.FileHandler('flux-api.log')
        fh.setFormatter(formatter)
        self.logger.addHandler(fh)

    def check_comfy_status(self) -> bool:
        """Verify ComfyUI service availability"""
        try:
            req = urllib.request.Request(
                f"{self.base_url}/history",
                method='GET'
            )
            with urllib.request.urlopen(req, timeout=10) as response:
                return response.status == 200
        except Exception as e:
            self.logger.error(f"ComfyUI status check failed: {str(e)}")
            return False

    def load_workflow(self, model_type: str) -> Dict[str, Any]:
        """Load workflow template from JSON file"""
        workflow_path = self.workflow_paths.get(model_type.lower())
        if not workflow_path:
            raise FluxAPIError(
                f"Invalid model type: {model_type}",
                FluxErrorCode.INVALID_INPUT
            )

        try:
            with open(workflow_path, 'r') as f:
                workflow = json.load(f)
            self.logger.debug(f"Loaded {model_type} workflow")
            return workflow
        except Exception as e:
            self.logger.error(f"Workflow load error: {str(e)}")
            raise FluxAPIError(
                f"Failed to load workflow: {str(e)}",
                FluxErrorCode.WORKFLOW_ERROR
            )

    def set_workflow_parameter(self, 
                             workflow: Dict[str, Any],
                             node_class: str,
                             parameter: str,
                             value: Any) -> None:
        """Generic workflow parameter setter"""
        for node_id, node in workflow.items():
            if node["class_type"] == node_class:
                node["inputs"][parameter] = value
                self.logger.debug(f"Set {node_class}.{parameter} = {value}")
                return
        raise FluxAPIError(
            f"{node_class} node not found in workflow",
            FluxErrorCode.WORKFLOW_ERROR
        )

    def modify_workflow(self,
                       workflow: Dict[str, Any],
                       prompt: str,
                       lora_name: Optional[str],
                       model_type: str,
                       seed: Optional[int] = None,
                       negative_prompt: Optional[str] = None,
                       width: int = 1024,
                       height: int = 1024) -> Dict[str, Any]:
        """Configure workflow parameters with validation"""
        try:
            # Set core parameters
            self.set_workflow_parameter(workflow, "CLIPTextEncode", "text", prompt)
            
            # Negative prompt handling
            if negative_prompt:
                self.set_workflow_parameter(
                    workflow, 
                    "CLIPTextEncodeNegative", 
                    "text", 
                    negative_prompt
                )

            # Random seed handling
            if seed is None:
                seed = random.randint(0, 2**32 - 1)
            self.set_workflow_parameter(workflow, "RandomNoise", "noise_seed", seed)

            # LoRA configuration
            if lora_name and lora_name.lower() != "none":
                if not self._verify_lora(lora_name):
                    available_loras = self.list_available_loras()
                    raise FluxAPIError(
                        f"LoRA '{lora_name}' not found. Available: {', '.join(available_loras)}",
                        FluxErrorCode.LORA_NOT_FOUND
                    )
                self.set_workflow_parameter(workflow, "LoraLoader", "lora_name", lora_name)
                self.set_workflow_parameter(workflow, "LoraLoader", "strength_model", 1.0)
                self.set_workflow_parameter(workflow, "LoraLoader", "strength_clip", 1.0)
            else:
                self.set_workflow_parameter(workflow, "LoraLoader", "strength_model", 0.0)
                self.set_workflow_parameter(workflow, "LoraLoader", "strength_clip", 0.0)

            return workflow

        except FluxAPIError:
            raise
        except Exception as e:
            self.logger.error(f"Workflow modification failed: {str(e)}")
            raise FluxAPIError(
                "Failed to configure workflow parameters",
                FluxErrorCode.WORKFLOW_ERROR
            )

    def _verify_lora(self, lora_name: str) -> bool:
        """Check for valid LoRA file with common extensions"""
        base_name = os.path.splitext(lora_name)[0]
        for ext in ['.safetensors', '.pt', '.ckpt']:
            if os.path.exists(os.path.join(self.lora_dir, base_name + ext)):
                return True
        return False

    def list_available_loras(self) -> List[str]:
        """Scan LoRA directory for valid model files"""
        try:
            return [
                f for f in os.listdir(self.lora_dir)
                if f.endswith(('.safetensors', '.pt', '.ckpt'))
            ]
        except Exception as e:
            self.logger.error(f"LoRA scan failed: {str(e)}")
            return []

    def _create_websocket_connection(self) -> websocket.WebSocket:
        """Establish WebSocket connection with retries"""
        for attempt in range(MAX_RETRIES):
            try:
                ws = websocket.WebSocket()
                ws.connect(self.ws_url)
                self.logger.debug("WebSocket connection established")
                return ws
            except Exception as e:
                if attempt < MAX_RETRIES - 1:
                    self.logger.warning(
                        f"WebSocket connection failed (attempt {attempt+1}): {str(e)}"
                    )
                    time.sleep(RETRY_DELAY)
                    continue
                raise FluxAPIError(
                    f"Failed to connect to ComfyUI: {str(e)}",
                    FluxErrorCode.CONNECTION_ERROR
                )

    def _queue_prompt(self, workflow: Dict[str, Any], client_id: str) -> str:
        """Submit workflow to ComfyUI for processing"""
        try:
            data = json.dumps({
                "prompt": workflow,
                "client_id": client_id
            }).encode('utf-8')

            req = urllib.request.Request(
                f"{self.base_url}/prompt",
                data=data,
                headers={'Content-Type': 'application/json'}
            )

            with urllib.request.urlopen(req) as response:
                result = json.loads(response.read().decode('utf-8'))
                return result['prompt_id']

        except Exception as e:
            self.logger.error(f"Prompt queueing failed: {str(e)}")
            raise FluxAPIError(
                "Failed to submit workflow to ComfyUI",
                FluxErrorCode.CONNECTION_ERROR
            )

    def _monitor_generation(self, ws: websocket.WebSocket, prompt_id: str) -> str:
        """Monitor workflow execution progress via WebSocket and return saved image filename"""
        self.logger.info("Connected to WebSocket, waiting for processing to complete...")
        
        finished_nodes = []
        image_saved = False
        image_filename = None
        
        try:
            while True:
                out = ws.recv()
                if isinstance(out, str):
                    try:
                        message = json.loads(out)
                        
                        if message["type"] == "executing":
                            data = message["data"]
                            node_id = data["node"]
                            
                            if node_id not in finished_nodes:
                                finished_nodes.append(node_id)
                                node_name = self.workflow.get(str(node_id), {}).get('_meta', {}).get('title', 'Unknown')
                                self.logger.info(f"Processing node {node_id}: {node_name}")
                            
                            if node_id is None and data["prompt_id"] == prompt_id:
                                return self._handle_completion(image_saved, image_filename, prompt_id)
                                
                        elif message["type"] == "executed":
                            outputs = message.get("data", {}).get("output", {})
                            image_filename = self._process_executed_message(outputs)
                            if image_filename:
                                image_saved = True
                                
                        elif message["type"] == "execution_error":
                            error = message.get('data', {}).get('exception_message', 'Unknown error')
                            raise FluxAPIError(f"Workflow execution error: {error}", 
                                             FluxErrorCode.GENERATION_FAILED)
                            
                    except json.JSONDecodeError:
                        continue
                        
        except websocket.WebSocketConnectionClosedException as e:
            self.logger.error(f"WebSocket connection closed: {e}")
            raise FluxAPIError("WebSocket connection closed unexpectedly", 
                             FluxErrorCode.CONNECTION_ERROR)
            
        finally:
            ws.close()
        
        return self._handle_completion(image_saved, image_filename, prompt_id)

    def _handle_completion(self, image_saved: bool, image_filename: Optional[str], prompt_id: str) -> str:
        """Handle post-execution completion logic"""
        if not image_saved:
            self.logger.warning("Image not found via WebSocket, checking history...")
            history = self._get_prompt_history(prompt_id)
            image_filename = self._extract_image_filename(history)
        
        if not image_filename:
            raise FluxAPIError("No output image generated", FluxErrorCode.GENERATION_FAILED)
            
        return image_filename

    def _get_prompt_history(self, prompt_id: str) -> dict:
        """Retrieve prompt execution history from ComfyUI"""
        try:
            req = urllib.request.Request(f"{self.base_url}/history/{prompt_id}")
            with urllib.request.urlopen(req) as response:
                return json.loads(response.read().decode('utf-8'))
        except Exception as e:
            self.logger.error(f"History retrieval failed: {str(e)}")
            return {}

    def _extract_image_filename(self, history: dict) -> Optional[str]:
        """Extract filename from ComfyUI history"""
        try:
            for prompt in history.values():
                for node in prompt.get('outputs', {}).values():
                    if 'images' in node:
                        for image in node['images']:
                            return image['filename']
            return None
        except Exception as e:
            self.logger.error(f"History parsing failed: {str(e)}")
            return None

    def generate_image(self,
                      prompt: str,
                      lora_name: Optional[str] = None,
                      model_type: str = "dev",
                      seed: Optional[int] = None,
                      negative_prompt: Optional[str] = None,
                      width: int = 1024,
                      height: int = 1024) -> str:
        """Main method to process text-to-image generation"""
        # Check rate limit
        if not self.rate_limiter.is_allowed():
            raise FluxAPIError("Rate limit exceeded. Please try again later.",
                             FluxErrorCode.RATE_LIMIT)

        request_id = str(uuid.uuid4())
        self.logger.info(f"Starting generation {request_id}")

        try:
            # Load and modify workflow
            self.workflow = self.load_workflow(model_type)
            self.workflow = self.modify_workflow(
                workflow=self.workflow,
                prompt=prompt,
                lora_name=lora_name,
                model_type=model_type,
                seed=seed,
                negative_prompt=negative_prompt,
                width=width,
                height=height
            )

            # Open websocket connection
            ws = self._create_websocket_connection()
            client_id = str(uuid.uuid4())
            
            # Queue the prompt
            prompt_id = self._queue_prompt(self.workflow, client_id)
            self.logger.debug(f"Prompt ID: {prompt_id}")

            # Monitor execution and get filename
            filename = self._monitor_generation(ws, prompt_id)
            
            if not filename:
                raise FluxAPIError(
                    "No output filename received from ComfyUI",
                    FluxErrorCode.GENERATION_FAILED
                )
                
            # Return the filename
            return filename

        except Exception as e:
            self.logger.error(f"Generation failed: {str(e)}")
            raise
        finally:
            if 'ws' in locals():
                ws.close()
            self.logger.info(f"Completed generation {request_id}")
   
    def get_system_info(self) -> Dict[str, Any]:
        """Get system status information"""
        try:
            comfyui_available = self.check_comfy_status()
            loras = self.list_available_loras()
            
            return {
                'status': 'healthy' if comfyui_available else 'unhealthy',
                'comfyui_available': comfyui_available,
                'active_workers': 1,
                'gpu_available': True,
                'loras_available': len(loras),
                'rate_limit': {
                    'max_requests': self.rate_limiter.max_requests,
                    'time_window': self.rate_limiter.time_window,
                    'remaining_tokens': self.rate_limiter.get_remaining_tokens()
                }
            }
        except Exception as e:
            self.logger.error(f"Error getting system info: {str(e)}")
            return {
                'status': 'degraded',
                'comfyui_available': False,
                'active_workers': 0,
                'gpu_available': False,
                'loras_available': 0,
                'rate_limit': {
                    'max_requests': 1,
                    'time_window': 1,
                    'remaining_tokens': 0.0
                }
            }

    def load_config(self, config_path: str) -> None:
        """Load configuration settings from a JSON file"""
        try:
            with open(config_path, 'r') as f:
                config = json.load(f)
                
            # Update paths and settings
            self.lora_dir = config.get('lora_directory', self.lora_dir)
            if 'workflow_paths' in config:
                self.workflow_paths.update(config['workflow_paths'])
            
            # Optional rate limiting settings
            if 'rate_limit' in config:
                self.rate_limiter = RateLimiter(
                    config['rate_limit'].get('max_requests', 10),
                    config['rate_limit'].get('time_window', 60)
                )
            
            self.logger.info(f"Configuration loaded from {config_path}")
        except Exception as e:
            self.logger.error(f"Error loading config: {str(e)}")
            raise FluxAPIError(
                f"Failed to load config: {str(e)}",
                FluxErrorCode.WORKFLOW_ERROR
            )
