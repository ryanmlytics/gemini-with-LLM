"""
AIGC MVP API Server
Replaces Vext API with Google Gemini backend
Maintains compatibility with existing Laravel client
"""

import os
import json
import hashlib
import time
import logging
from typing import Optional, List, Dict, Any
from datetime import datetime
from contextlib import asynccontextmanager
from urllib.parse import unquote

from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
from fastapi.middleware.cors import CORSMiddleware
from fastapi.exceptions import RequestValidationError
from fastapi import status
from pydantic import BaseModel
from dotenv import load_dotenv
from sse_starlette.sse import EventSourceResponse

from services.gemini_service import GeminiService
from services.search_service import SearchService
from services.cache_service import CacheService
from services.content_service import ContentService

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Initialize services
gemini_service = GeminiService()
search_service = SearchService()
cache_service = CacheService()
content_service = ContentService()

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info("Starting AIGC MVP API Server")
    yield
    # Shutdown
    logger.info("Shutting down AIGC MVP API Server")

app = FastAPI(
    title="AIGC MVP API",
    description="LLM API Server with Gemini backend",
    version="1.0.0",
    lifespan=lifespan
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure appropriately for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Request/Response Models (matching Laravel contract)

class GenerateQuestionsInput(BaseModel):
    url: Optional[str] = None
    context: Optional[str] = None
    prompt: Optional[str] = None
    lang: Optional[str] = "zh-tw"
    previous_questions: Optional[List[str]] = None
    
    def __init__(self, **data):
        # Convert empty string to empty list for previous_questions
        if 'previous_questions' in data and data['previous_questions'] == '':
            data['previous_questions'] = []
        # Convert None to empty list
        if 'previous_questions' not in data or data['previous_questions'] is None:
            data['previous_questions'] = []
        super().__init__(**data)

class GenerateQuestionsRequest(BaseModel):
    inputs: GenerateQuestionsInput
    user: str = "uuid_user"
    type: Optional[str] = "answer_page"
    source_url: Optional[str] = None

class GetMetadataInput(BaseModel):
    query: Optional[str] = ""
    url: Optional[str] = None
    tag_prompt: Optional[str] = ""

class GetMetadataRequest(BaseModel):
    inputs: GetMetadataInput
    user: str = "uuid_user"

class GetAnswerInput(BaseModel):
    query: str = ""
    url: Optional[str] = ""
    prompt: Optional[str] = ""
    content_id: Optional[str] = ""
    lang: Optional[str] = "zh-tw"

class GetAnswerRequest(BaseModel):
    inputs: GetAnswerInput
    user: str = "uuid_user"
    stream: Optional[bool] = False

# Helper functions

def generate_uuid(key: str) -> str:
    """Generate UUID from key string"""
    return hashlib.sha256(key.encode()).hexdigest()

def get_cache_key(endpoint: str, inputs: Dict, user: str = "") -> str:
    """Generate cache key for endpoint (sanitized for filesystem compatibility)"""
    key_parts = [endpoint, json.dumps(inputs, sort_keys=True), user]
    key = ":".join(key_parts)
    # Use hash only to avoid invalid filesystem characters on Windows/Linux
    hash_key = hashlib.sha256(key.encode()).hexdigest()
    # Sanitize: replace colons with underscores for filesystem compatibility
    return f"ai_{endpoint}_{hash_key}"

# Endpoints

@app.post("/generateQuestions")
async def generate_questions(request: GenerateQuestionsRequest):
    """
    Generate 1-5 structured questions from content or URL
    Matches existing Vext API contract
    """
    start_time = time.time()
    
    logger.info(f"Received generateQuestions request from user: {request.user}")
    logger.debug(f"Request data: {request.model_dump()}")

    try:
        inputs = request.inputs
        
        # Decode URL-encoded URLs
        if inputs.url:
            inputs.url = unquote(inputs.url)
        if inputs.context:
            inputs.context = unquote(inputs.context)

        # Validate input
        if not inputs.url and not inputs.context:
            raise HTTPException(
                status_code=400,
                detail="Either url or context must be provided"
            )
        
        # Generate cache key
        cache_key = get_cache_key(
            "questions",
            {
                "url": inputs.url or "",
                "context": inputs.context or "",
                "lang": inputs.lang,
                "type": request.type or "",
                "source_url": request.source_url or ""
            },
            request.user
        )
        
        # Check cache
        cached_result = await cache_service.get(cache_key)
        if cached_result:
            logger.info(f"Cache hit for questions: {cache_key[:20]}...")
            return JSONResponse(content=cached_result)
        
        # Get content if URL provided
        content_text = inputs.context
        if inputs.url and not content_text:
            content_text = await content_service.fetch_content(inputs.url)
        
        # Generate questions using Gemini

        questions_result = await gemini_service.generate_questions(
            content=content_text or "",
            lang=inputs.lang or "zh-tw",
            max_questions=5,
            previous_questions=inputs.previous_questions or []
        )
        
        # Build response matching existing format
        response = {
            "event": "workflow_finished",
            "data": {
                "outputs": {
                    "result": questions_result.get("questions", []),
                    "content_id": questions_result.get("content_id"),
                },
                "provider": "gemini-2.5-flash-lite",
                "meta": {
                    "tokens_used": questions_result.get("tokens_used", 0),
                    "latency_ms": int((time.time() - start_time) * 1000),
                    "cached": False
                }
            }
        }
        
        # Cache result (10 minutes)
        await cache_service.set(cache_key, response, ttl=600)
        
        return JSONResponse(content=response)
        
    except ValueError as e:
        # Location restriction, connection timeout, or configuration error
        error_msg = str(e)
        if "location is not supported" in error_msg.lower() or "region" in error_msg.lower():
            logger.error(f"Gemini API location restriction: {error_msg}")
            raise HTTPException(
                status_code=503,
                detail="Gemini API is not available in this region. Please use VPN or deploy to a supported region."
            )
        elif "cannot connect" in error_msg.lower() or "connection" in error_msg.lower():
            logger.error(f"Gemini API connection error: {error_msg}")
            raise HTTPException(
                status_code=503,
                detail="Cannot connect to Gemini API. Please check your network connection, firewall settings, or use VPN if Google services are blocked in your region."
            )
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error generating questions: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Internal server error: {str(e)}"
        )

@app.post("/getMetadata")
async def get_metadata(request: GetMetadataRequest):
    """
    Return canonical sources, tags, images and citation hints
    Matches existing Vext API contract
    """
    start_time = time.time()
    
    logger.info(f"Received getMetadata request from user: {request.user}")
    logger.debug(f"Request data: {request.model_dump()}")

    try:
        inputs = request.inputs
        
        # Decode URL-encoded URLs
        if inputs.url:
            inputs.url = unquote(inputs.url)
        
        if not inputs.url:
            raise HTTPException(
                status_code=400,
                detail="URL is required"
            )
        
        # Generate cache key
        cache_key = get_cache_key(
            "metadata",
            {"url": inputs.url, "query": inputs.query or ""},
            request.user
        )
        
        # Check cache
        cached_result = await cache_service.get(cache_key)
        if cached_result:
            logger.info(f"Cache hit for metadata: {cache_key[:20]}...")
            return JSONResponse(content=cached_result)
        
        # Fetch content and metadata
        metadata_result = await search_service.get_metadata(
            url=inputs.url,
            query=inputs.query or "",
            tag_prompt=inputs.tag_prompt
        )
        
        # Build response matching existing format
        response = {
            "event": "workflow_finished",
            "data": {
                "outputs": {
                    "url": inputs.url,
                    "domain": metadata_result.get("domain", ""),
                    "title": metadata_result.get("title", ""),
                    "summary": metadata_result.get("summary", ""),
                    "sources": metadata_result.get("sources", []),
                    "tags": metadata_result.get("tags", []),
                    "images": metadata_result.get("images", [])
                },
                "provider": "gemini-2.5-flash",
                "meta": {
                    "tokens_used": metadata_result.get("tokens_used", 0),
                    "latency_ms": int((time.time() - start_time) * 1000),
                    "cached": False,
                    "search_api_quota_used": metadata_result.get("search_quota", 0)
                }
            }
        }
        
        # Cache result (1 hour)
        await cache_service.set(cache_key, response, ttl=3600)
        
        return JSONResponse(content=response)
        
    except ValueError as e:
        # Location restriction, connection timeout, or configuration error
        error_msg = str(e)
        if "location is not supported" in error_msg.lower() or "region" in error_msg.lower():
            logger.error(f"Gemini API location restriction: {error_msg}")
            raise HTTPException(
                status_code=503,
                detail="Gemini API is not available in this region. Please use VPN or deploy to a supported region."
            )
        elif "cannot connect" in error_msg.lower() or "connection" in error_msg.lower():
            logger.error(f"Gemini API connection error: {error_msg}")
            raise HTTPException(
                status_code=503,
                detail="Cannot connect to Gemini API. Please check your network connection, firewall settings, or use VPN if Google services are blocked in your region."
            )
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error getting metadata: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Internal server error: {str(e)}"
        )

@app.post("/getAnswer")
async def get_answer(request: GetAnswerRequest):
    """
    Generate grounded, analytical answer with optional SSE streaming
    Matches existing Vext API contract
    """
    start_time = time.time()
    
    logger.info(f"Received getAnswer request from user: {request.user}, stream: {request.stream}")
    logger.debug(f"Request data: {request.model_dump()}")

    try:
        inputs = request.inputs
        
        # Decode URL-encoded URLs
        if inputs.url:
            inputs.url = unquote(inputs.url)
        
        # Validate input
        if not inputs.query:
            raise HTTPException(
                status_code=400,
                detail="Query is required"
            )
        
        # If content_id provided, fetch content; otherwise use URL
        content_text = ""
        if inputs.content_id:
            content_text = await content_service.get_content(inputs.content_id)
        elif inputs.url:
            content_text = await content_service.fetch_content(inputs.url)

        # Streaming response
        if request.stream:
            async def stream_answer():
                try:
                    # Send workflow event
                    event_data = json.dumps({
                        "stage": "retrieved_content",
                        "ts": datetime.utcnow().isoformat() + "Z"
                    })
                    yield f"event: workflow_started\ndata: {event_data}\n\n"
                    
                    # Stream answer from Gemini
                    full_answer = ""
                    async for chunk in gemini_service.stream_answer(
                        content=content_text,
                        question=inputs.query,
                        prompt=inputs.prompt or "",
                        lang=inputs.lang or "zh-tw"
                    ):
                        full_answer += chunk
                        chunk_data = json.dumps({"chunk": chunk})
                        yield f"event: token_chunk\ndata: {chunk_data}\n\n"
                    
                    # Extract citations
                    citations = await gemini_service.extract_citations(
                        answer=full_answer,
                        sources=[]  # Can be enhanced with actual sources
                    )
                    
                    citations_data = json.dumps({"citations": citations})
                    yield f"event: citations\ndata: {citations_data}\n\n"
                    
                    # Send final event
                    final_data = json.dumps({
                        "outputs": {
                            "result": full_answer
                        },
                        "provider": "gemini-2.5-flash",
                        "meta": {
                            "tokens_used": len(full_answer.split()),  # Approximate
                            "latency_ms": int((time.time() - start_time) * 1000),
                            "cached": False
                        }
                    })

                    yield f"event: workflow_finished\ndata: {final_data}\n\n"
                    
                except Exception as e:
                    logger.error(f"Streaming error: {str(e)}", exc_info=True)
                    error_data = json.dumps({"error": str(e)})
                    yield f"event: error\ndata: {error_data}\n\n"
            
            return EventSourceResponse(stream_answer())
        
        # Non-streaming response
        else:
            # Generate cache key
            cache_key = get_cache_key(
                "answer",
                {
                    "query": inputs.query,
                    "content_id": inputs.content_id or "",
                    "url": inputs.url or "",
                    "lang": inputs.lang
                },
                request.user
            )
            
            # Check cache
            cached_result = await cache_service.get(cache_key)
            if cached_result:
                logger.info(f"Cache hit for answer: {cache_key[:20]}...")
                return JSONResponse(content=cached_result)
            
            # Generate answer
            answer_result = await gemini_service.generate_answer(
                content=content_text,
                question=inputs.query,
                prompt=inputs.prompt or "",
                lang=inputs.lang or "zh-tw",
                max_tokens=800
            )
            
            # Build response matching existing format
            response = {
                "event": "workflow_finished",
                "data": {
                    "outputs": {
                        "result": answer_result.get("answer", "")
                    },
                    "provider": "gemini-2.5-flash",
                    "meta": {
                        "tokens_used": answer_result.get("tokens_used", 0),
                        "latency_ms": int((time.time() - start_time) * 1000),
                        "cached": False
                    }
                }
            }
            
            # Cache result (5 minutes)
            await cache_service.set(cache_key, response, ttl=300)
            
            return JSONResponse(content=response)
            
    except ValueError as e:
        # Location restriction, connection timeout, or configuration error
        error_msg = str(e)
        if "location is not supported" in error_msg.lower() or "region" in error_msg.lower():
            logger.error(f"Gemini API location restriction: {error_msg}")
            raise HTTPException(
                status_code=503,
                detail="Gemini API is not available in this region. Please use VPN or deploy to a supported region."
            )
        elif "cannot connect" in error_msg.lower() or "connection" in error_msg.lower():
            logger.error(f"Gemini API connection error: {error_msg}")
            raise HTTPException(
                status_code=503,
                detail="Cannot connect to Gemini API. Please check your network connection, firewall settings, or use VPN if Google services are blocked in your region."
            )
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error(f"Error getting answer: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Internal server error: {str(e)}"
        )

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Handle validation errors with detailed messages"""
    logger.error(f"Validation error on {request.url.path}: {exc.errors()}")
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "detail": exc.errors(),
            "message": "Request validation failed. Please check your request format."
        }
    )

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "timestamp": datetime.utcnow().isoformat()}

# if __name__ == "__main__":
#     import uvicorn
#     uvicorn.run(app, host="0.0.0.0", port=8888)

