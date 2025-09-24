from fastapi import FastAPI, HTTPException, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.responses import StreamingResponse
from pydantic import BaseModel
from typing import Optional, List, Dict, Any, Union
import uvicorn
import os
from phenoml import AsyncClient
import asyncio
from dotenv import load_dotenv
import time
import hashlib
import json

# Load environment variables from .env file
load_dotenv()

app = FastAPI(title="PhenoML VAPI Integration", version="1.0.0")

# Initialize PhenoML client
phenoml_client = None

# Simple in-memory session store 
session_store = {}

# Security for API key authentication
security = HTTPBearer()

async def initialize_phenoml_client():
    """Initialize the AsyncClient"""
    global phenoml_client
    
    username = os.getenv("PHENOML_USERNAME")
    password = os.getenv("PHENOML_PASSWORD")
    base_url = os.getenv("PHENOML_BASE_URL")
    agent_id = os.getenv("PHENOML_VOICE_AGENT_ID")
    
    if not username or not password:
        raise ValueError("PHENOML_USERNAME and PHENOML_PASSWORD environment variables are required")
    if not agent_id:
        raise ValueError("PHENOML_AGENT_ID environment variable is required")
    
    print(f"Agent ID: {agent_id}")
    
    # Create AsyncClient
    phenoml_client = AsyncClient(
        username=username,
        password=password,
        base_url=base_url
    )
    
    await phenoml_client.initialize()
    print("✓ AsyncClient initialized successfully")
    return phenoml_client

def get_phenoml_client():
    """Get the already initialized client"""
    global phenoml_client
    if phenoml_client is None:
        raise RuntimeError("PhenoML client not initialized. Call initialize_phenoml_client() first.")
    return phenoml_client

# Add CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins for VAPI. Don't do this in production!
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["*"],
)

# Initialize PhenoML client on startup  
@app.on_event("startup")
async def startup_event():
    """Initialize PhenoML client when server starts"""
    try:
        await initialize_phenoml_client()
        print("Server startup complete - PhenoML AsyncClient ready")
    except Exception as e:
        print(f"Failed to initialize PhenoML client on startup: {e}")
        raise

# VAPI Message format
class VapiMessage(BaseModel):
    role: str  # "system", "user", "assistant"
    content: str

# VAPI Chat Completions Request
class VapiChatRequest(BaseModel):
    model: Optional[str] = "phenoml"
    messages: List[VapiMessage]
    max_tokens: Optional[int] = None
    temperature: Optional[float] = None
    stream: Optional[bool] = False

# VAPI Chat Completions Response
class VapiChoice(BaseModel):
    index: int
    message: VapiMessage
    finish_reason: str

class VapiUsage(BaseModel):
    prompt_tokens: int
    completion_tokens: int
    total_tokens: int

class VapiChatResponse(BaseModel):
    id: str
    object: str = "chat.completion"
    created: int
    model: str
    choices: List[VapiChoice]
    usage: VapiUsage

def verify_api_key(credentials: HTTPAuthorizationCredentials = Depends(security)):
    """Verify API key authentication"""
    expected_api_key = os.getenv("VAPI_API_KEY")
    if not expected_api_key:
        # If no API key is set, allow all requests (for development)
        return True
    
    if credentials.credentials != expected_api_key:
        raise HTTPException(status_code=401, detail="Invalid API key")
    return True

@app.get("/health")
async def health_check():
    return {"status": "healthy"}

@app.post("/chat/completions")
async def chat_completions(request: VapiChatRequest, authenticated: bool = Depends(verify_api_key)):
    try:
        # Extract the latest user message from the conversation
        user_messages = [msg for msg in request.messages if msg.role == "user"]
        if not user_messages:
            raise HTTPException(status_code=400, detail="No user message found")
        
        latest_message = user_messages[-1].content
        
        # Use a simple conversation identifier - hash of first user message
        first_user_msg = next((msg for msg in request.messages if msg.role == "user"), None)
        if not first_user_msg:
            raise HTTPException(status_code=400, detail="No user message found for conversation ID")
            
        conversation_key = hashlib.md5(first_user_msg.content.encode()).hexdigest()
        
        # Look up existing PhenoML session_id
        phenoml_session_id = session_store.get(conversation_key)
        
        # Create fresh client for each request
        username = os.getenv("PHENOML_USERNAME")
        password = os.getenv("PHENOML_PASSWORD") 
        base_url = os.getenv("PHENOML_BASE_URL")
        agent_id = os.getenv("PHENOML_VOICE_AGENT_ID")
        
        client = AsyncClient(
            username=username,
            password=password,
            base_url=base_url
        )
        await client.initialize()
        
        # Call PhenoML agent chat endpoint
        chat_params = {
            "agent_id": agent_id,
            "message": latest_message
        }
        
        # Include session_id if we have one from previous interactions
        if phenoml_session_id:
            chat_params["session_id"] = phenoml_session_id
            print(f"Using existing PhenoML session_id: {phenoml_session_id}")
        
        # Make the chat request to PhenoML using AsyncClient
        print(f"Calling PhenoML AsyncClient with params: {chat_params}")
        response_data = await client.agent.chat(**chat_params)
        print(f"PhenoML response: {response_data}")
        
        # Extract response text and session_id
        if hasattr(response_data, 'response'):
            response_text = response_data.response
            new_session_id = getattr(response_data, 'session_id', None)
        elif isinstance(response_data, dict):
            response_text = response_data.get("response", str(response_data))
            new_session_id = response_data.get("session_id")
        else:
            response_text = str(response_data)
            new_session_id = None
        
        # Store the session_id for future requests using current conversation key
        if new_session_id:
            session_store[conversation_key] = new_session_id
            print(f"Stored PhenoML session_id {new_session_id} for key {conversation_key}")
        
        # Format response exactly like OpenAI API
        openai_response = {
            "id": f"chatcmpl-{int(time.time())}",
            "object": "chat.completion", 
            "created": int(time.time()),
            "model": request.model or "phenoml",
            "choices": [
                {
                    "index": 0,
                    "message": {
                        "role": "assistant",
                        "content": response_text
                    },
                    "finish_reason": "stop"
                }
            ],
            "usage": {
                "prompt_tokens": len(latest_message.split()),
                "completion_tokens": len(response_text.split()), 
                "total_tokens": len(latest_message.split()) + len(response_text.split())
            }
        }
        
        # Check if streaming is requested
        if getattr(request, 'stream', False):
            # Return streaming response
            async def generate_stream():
                # For simplicity, just send the complete response as a single chunk
                chunk = {
                    "id": f"chatcmpl-{int(time.time())}",
                    "object": "chat.completion.chunk",
                    "created": int(time.time()),
                    "model": request.model or "phenoml",
                    "choices": [
                        {
                            "index": 0,
                            "delta": {
                                "role": "assistant",
                                "content": response_text
                            },
                            "finish_reason": "stop"
                        }
                    ]
                }
                yield f"data: {json.dumps(chunk)}\n\n"
                yield "data: [DONE]\n\n"
            
            return StreamingResponse(generate_stream(), media_type="text/event-stream")
        else:
            return openai_response
        
    except ValueError as e:
        print(f"Configuration error: {e}")
        raise HTTPException(status_code=500, detail="Chat service not properly configured")
        
    except Exception as e:
        print(f"Error with PhenoML API: {e}")
        raise HTTPException(status_code=500, detail="Internal server error")

# Clean shutdown
@app.on_event("shutdown")
async def shutdown_event():
    global phenoml_client
    if phenoml_client:
        try:
            if hasattr(phenoml_client, 'close'):
                await phenoml_client.close()
        except Exception as e:
            print(f"Error closing PhenoML client: {e}")

if __name__ == "__main__":
    uvicorn.run("app_voice:app", host="0.0.0.0", port=8002, reload=True)