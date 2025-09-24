from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from typing import Optional
import uvicorn
import os
from phenoml import AsyncClient
import asyncio
from dotenv import load_dotenv

# Load environment variables from .env file
load_dotenv()

app = FastAPI(title="PhenoML Chat Demo", version="1.0.0")

# Initialize PhenoML client
phenoml_client = None

async def initialize_phenoml_client():
    """Initialize the AsyncClient"""
    global phenoml_client
    
    username = os.getenv("PHENOML_USERNAME")
    password = os.getenv("PHENOML_PASSWORD")
    base_url = os.getenv("PHENOML_BASE_URL")
    agent_id = os.getenv("PHENOML_AGENT_ID")
   
    
    if not username or not password:
        raise ValueError("PHENOML_USERNAME and PHENOML_PASSWORD environment variables are required")
    if not agent_id:
        raise ValueError("PHENOML_AGENT_ID environment variable is required")
    
    # print(f"Initializing AsyncClient with base_url: {base_url}")
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

# Add CORS middleware - configured for development
app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://localhost:5173",  # Vite dev server
        "http://localhost:3000",  # Common React dev port
        "http://127.0.0.1:5173",
        "http://127.0.0.1:3000",
    ],
    allow_credentials=True,
    allow_methods=["GET", "POST"],
    allow_headers=["Content-Type", "Authorization"],
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

class ChatMessage(BaseModel):
    message: str
    session_id: Optional[str] = None

class ChatResponse(BaseModel):
    response: str
    session_id: str

@app.get("/health")
async def health_check():
    return {"status": "healthy"}

@app.post("/chat", response_model=ChatResponse)
async def chat_endpoint(chat_message: ChatMessage):
    try:
        # Create fresh client for each request to avoid state issues
        username = os.getenv("PHENOML_USERNAME")
        password = os.getenv("PHENOML_PASSWORD") 
        base_url = os.getenv("PHENOML_BASE_URL")
        agent_id = os.getenv("PHENOML_AGENT_ID")
        
        client = AsyncClient(
            username=username,
            password=password,
            base_url=base_url
        )
        await client.initialize()
        
        # Call PhenoML agent chat endpoint
        chat_params = {
            "agent_id": agent_id,
            "message": chat_message.message
        }
        
        # Only include session_id if it exists (for subsequent messages)
        if chat_message.session_id:
            chat_params["session_id"] = chat_message.session_id
        
        # Make the chat request to PhenoML using AsyncClient
        print(f"Calling PhenoML AsyncClient with params: {chat_params}")
        response_data = await client.agent.chat(**chat_params)
        print(f"PhenoML response: {response_data}")  # Debug
        
        # The response format might be different - let's handle both cases
        if hasattr(response_data, 'response'):
            response_text = response_data.response
            session_id = getattr(response_data, 'session_id', None) or chat_message.session_id
        elif isinstance(response_data, dict):
            response_text = response_data.get("response", str(response_data))
            session_id = response_data.get("session_id") or chat_message.session_id
        else:
            # Fallback if response is a string or other format
            response_text = str(response_data)
            session_id = chat_message.session_id
        
        return ChatResponse(response=response_text, session_id=session_id)
        
    except ValueError as e:
        # Environment variable configuration errors
        print(f"Configuration error: {e}")
        return ChatResponse(
            response="Chat service is not properly configured. Please check environment variables.",
            session_id=chat_message.session_id or "config_error"
        )
        
    except Exception as e:
        # PhenoML API or other errors
        print(f"Error with PhenoML API: {e}")
        return ChatResponse(
            response="I'm experiencing technical difficulties. Please try again later.",
            session_id=chat_message.session_id or "error_session"
        )

# Clean shutdown
@app.on_event("shutdown")
async def shutdown_event():
    global phenoml_client
    if phenoml_client:
        # Close the AsyncClient if it has a close method
        try:
            if hasattr(phenoml_client, 'close'):
                await phenoml_client.close()
        except Exception as e:
            print(f"Error closing PhenoML client: {e}")

if __name__ == "__main__":
    uvicorn.run("app:app", host="127.0.0.1", port=8001, reload=True)