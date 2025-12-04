from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from typing import List, Dict, Any, Optional
import uvicorn
import os
import sys
import logging

# Add parent directory to path to import proxy_mcp
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from interactive_client import InteractiveClient, load_config

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = FastAPI()

# CORS configuration
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins for dev
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize MCP Client
config_path = os.path.join(os.path.dirname(__file__), "config.json")
config = load_config(config_path)
client = InteractiveClient(config)

# Start servers on startup
@app.on_event("startup")
async def startup_event():
    logger.info("Starting MCP servers...")
    client.start_servers()

@app.on_event("shutdown")
async def shutdown_event():
    logger.info("Stopping MCP servers...")
    client.cleanup()

class ChatRequest(BaseModel):
    messages: List[Dict[str, Any]]

@app.post("/api/chat")
async def chat(request: ChatRequest):
    try:
        result = client.process_message(request.messages)
        return result
    except Exception as e:
        logger.error(f"Error processing message: {e}")
        raise HTTPException(status_code=500, detail=str(e))

@app.get("/api/config")
async def get_config():
    # Return safe config (masking keys)
    safe_config = config.copy()
    if "openaiKey" in safe_config:
        safe_config["openaiKey"] = "sk-..." + safe_config["openaiKey"][-4:]
    return safe_config

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8000)
