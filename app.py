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
import uuid
from typing import Optional, List, Dict, Any
from datetime import datetime
from contextlib import asynccontextmanager
from urllib.parse import unquote

from fastapi import FastAPI, Request, HTTPException, Depends, Header
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

# Security configuration
API_BEARER_TOKEN = os.getenv("API_BEARER_TOKEN")

allowed_origins_env = os.getenv("ALLOWED_ORIGINS", "")
_parsed_origins = [origin.strip() for origin in allowed_origins_env.split(",") if origin.strip()]
if _parsed_origins:
    ALLOWED_ORIGINS = _parsed_origins
else:
    ALLOWED_ORIGINS = ["http://localhost", "http://localhost:3000"]
    logger.warning(
        "ALLOWED_ORIGINS not set; defaulting CORS policy to localhost origins only. "
        "Set ALLOWED_ORIGINS env var for production deployments."
    )

if not API_BEARER_TOKEN:
    logger.warning(
        "API_BEARER_TOKEN not set. Authentication checks will be skipped. "
        "Set this environment variable to enforce bearer-token access."
    )

# Initialize services
gemini_service = GeminiService()
search_service = SearchService()
cache_service = CacheService()
content_service = ContentService()


async def verify_bearer_token(authorization: str = Header(default=None)) -> None:
    """
    Verify bearer token from Authorization header when API_BEARER_TOKEN is configured.
    """
    if not API_BEARER_TOKEN:
        return

    if not authorization or not authorization.startswith("Bearer "):
        logger.warning("Unauthorized request: missing or malformed Authorization header")
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authorization header with Bearer token is required",
        )

    provided_token = authorization.split(" ", 1)[1].strip()
    if provided_token != API_BEARER_TOKEN:
        logger.warning("Forbidden request: invalid bearer token provided")
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Invalid API token",
        )

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
    allow_origins=ALLOWED_ORIGINS,
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

class EEATAssessmentInput(BaseModel):
    input_type: str  # "url" or "content"
    url: Optional[str] = None
    content: Optional[str] = None
    metadata: Optional[Dict[str, Any]] = None

class EEATAssessmentRequest(BaseModel):
    inputs: EEATAssessmentInput
    user: Optional[str] = "uuid_user"

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

@app.post("/generateQuestions", dependencies=[Depends(verify_bearer_token)])
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
        
        # Normalize empty strings to None for validation
        if inputs.url == "":
            inputs.url = None
        if inputs.context == "":
            inputs.context = None
        
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
            previous_questions=inputs.previous_questions or [],
            custom_prompt=inputs.prompt
        )
        
        # Generate content_id if not provided
        content_id = questions_result.get("content_id")
        if not content_id:
            # Generate content_id from context or URL
            content_source = inputs.context or inputs.url or ""
            if content_source:
                content_id = await content_service.reserve_content_id_from_url(content_source)
            else:
                content_id = str(uuid.uuid4())
        
        # Save content with content_id for later retrieval
        if content_text:
            await content_service.save_content(content_id, content_text, inputs.url or request.source_url)
        
        # Convert questions array to object format (question_1, question_2, etc.)
        questions_list = questions_result.get("questions", [])
        questions_dict = {}
        for i, question in enumerate(questions_list, 1):
            # Extract question text - handle both dict and string formats
            if isinstance(question, dict):
                question_text = question.get("text", question.get("question", str(question)))
            else:
                question_text = str(question)
            questions_dict[f"question_{i}"] = question_text
        
        # Calculate timestamps
        created_at = int(start_time)
        finished_at = int(time.time())
        elapsed_time = time.time() - start_time
        
        # Generate task_id
        task_id = str(uuid.uuid4())
        
        # Build response matching expected format
        response = {
            "task_id": task_id,
            "data": {
                "status": "succeeded",
                "outputs": {
                    "result": questions_dict,
                    "content_id": content_id
                },
                "elapsed_time": elapsed_time,
                "created_at": created_at,
                "finished_at": finished_at
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
    except HTTPException:
        # Re-raise HTTPException (don't convert to 500)
        raise
    except Exception as e:
        logger.error(f"Error generating questions: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Internal server error: {str(e)}"
        )

@app.post("/getMetadata", dependencies=[Depends(verify_bearer_token)])
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
        
        # Calculate timestamps
        created_at = int(start_time)
        finished_at = int(time.time())
        elapsed_time = time.time() - start_time
        
        # Generate task_id
        task_id = str(uuid.uuid4())
        
        # Format tag (single string, not array)
        tags_list = metadata_result.get("tags", [])
        tag = ", ".join(tags_list) if tags_list else ""
        
        # Format images as nested JSON string
        images_list = metadata_result.get("images", [])
        images_json = json.dumps({"images": images_list}, ensure_ascii=False, indent=2)
        images_output = [{"images": images_json}] if images_list else [{"images": json.dumps({"images": []}, ensure_ascii=False)}]
        
        # Format sources as nested JSON string with citations
        sources_list = metadata_result.get("sources", [])
        citations = [
            {
                "title": s.get("title", ""),
                "url": s.get("url", ""),
                "content": s.get("snippet", "")
            }
            for s in sources_list
        ]
        sources_json = json.dumps({"citations": citations}, ensure_ascii=False, indent=2)
        sources_output = [{"sources": sources_json}] if citations else [{"sources": json.dumps({"citations": []}, ensure_ascii=False)}]
        
        # Build response matching Vext API format from spec
        response = {
            "task_id": task_id,
            "data": {
                "status": "succeeded",
                "outputs": {
                    "tag": tag,
                    "images": images_output,
                    "sources": sources_output
                },
                "elapsed_time": elapsed_time,
                "created_at": created_at,
                "finished_at": finished_at
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
    except HTTPException:
        # Re-raise HTTPException (don't convert to 500)
        raise
    except Exception as e:
        logger.error(f"Error getting metadata: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Internal server error: {str(e)}"
        )

@app.post("/getAnswer", dependencies=[Depends(verify_bearer_token)])
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
            
            # Calculate timestamps
            created_at = int(start_time)
            finished_at = int(time.time())
            elapsed_time = time.time() - start_time
            
            # Generate task_id
            task_id = str(uuid.uuid4())
            
            # Build response matching Vext API format from spec
            response = {
                "event": "workflow_finished",
                "task_id": task_id,
                "data": {
                    "status": "succeeded",
                    "outputs": {
                        "result": answer_result.get("answer", "")
                    },
                    "elapsed_time": elapsed_time,
                    "created_at": created_at,
                    "finished_at": finished_at
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
    except HTTPException:
        # Re-raise HTTPException (don't convert to 500)
        raise
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

@app.post("/api/v1/content/eeat-assessment", dependencies=[Depends(verify_bearer_token)])
@app.post("/eeat", dependencies=[Depends(verify_bearer_token)])
async def eeat_assessment(request: EEATAssessmentRequest):
    """
    Assess E-E-A-T (Experience, Expertise, Authoritativeness, Trust) quality of content
    """
    start_time = time.time()
    
    logger.info(f"Received EEAT assessment request from user: {request.user}")
    logger.debug(f"Request data: {request.model_dump()}")
    
    try:
        inputs = request.inputs
        
        # Validate input_type
        if inputs.input_type not in ["url", "content"]:
            raise HTTPException(
                status_code=400,
                detail={
                    "status": "error",
                    "error": {
                        "code": "INVALID_INPUT",
                        "message": "input_type must be either 'url' or 'content'",
                        "details": {}
                    }
                }
            )
        
        # Validate that required field is provided
        if inputs.input_type == "url" and not inputs.url:
            raise HTTPException(
                status_code=400,
                detail={
                    "status": "error",
                    "error": {
                        "code": "INVALID_INPUT",
                        "message": "url is required when input_type is 'url'",
                        "details": {}
                    }
                }
            )
        if inputs.input_type == "content" and not inputs.content:
            raise HTTPException(
                status_code=400,
                detail={
                    "status": "error",
                    "error": {
                        "code": "INVALID_INPUT",
                        "message": "content is required when input_type is 'content'",
                        "details": {}
                    }
                }
            )
        
        # Decode URL-encoded URLs
        content_text = ""
        if inputs.input_type == "url":
            if inputs.url:
                inputs.url = unquote(inputs.url)
                content_text = await content_service.fetch_content(inputs.url)
                if not content_text:
                    raise HTTPException(
                        status_code=422,
                        detail={
                            "status": "error",
                            "error": {
                                "code": "CONTENT_FETCH_FAILED",
                                "message": "Unable to fetch content from the provided URL",
                                "details": {
                                    "url": inputs.url,
                                    "reason": "Content extraction failed or URL returned empty content"
                                }
                            }
                        }
                    )
        else:
            if inputs.content:
                content_text = inputs.content
        
        if not content_text:
            raise HTTPException(
                status_code=400,
                detail={
                    "status": "error",
                    "error": {
                        "code": "INVALID_INPUT",
                        "message": "No content available for assessment",
                        "details": {}
                    }
                }
            )
        
        # Generate cache key
        cache_key = get_cache_key(
            "eeat_assessment",
            {
                "input_type": inputs.input_type,
                "url": inputs.url or "",
                "content_hash": hashlib.sha256(content_text.encode()).hexdigest()[:16],
                "metadata": json.dumps(inputs.metadata or {}, sort_keys=True)
            },
            request.user or ""
        )
        
        # Check cache
        cached_result = await cache_service.get(cache_key)
        if cached_result:
            logger.info(f"Cache hit for EEAT assessment: {cache_key[:20]}...")
            return JSONResponse(content=cached_result)
        
        # Perform EEAT assessment
        assessment_result = await gemini_service.assess_eeat(
            content=content_text,
            metadata=inputs.metadata,
            lang="en"  # Can be made configurable if needed
        )
        
        # Calculate processing time
        processing_time_ms = int((time.time() - start_time) * 1000)
        
        # Build response matching spec format
        response = {
            "status": "success",
            "data": assessment_result,
            "metadata": {
                "analyzed_at": datetime.utcnow().isoformat() + "Z",
                "processing_time_ms": processing_time_ms,
                "content_length": len(content_text),
                "language": "en"  # Can detect language if needed
            }
        }
        
        # Cache result (1 hour)
        await cache_service.set(cache_key, response, ttl=3600)
        
        return JSONResponse(content=response)
        
    except HTTPException:
        # Re-raise HTTPException (don't convert to 500)
        raise
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
        logger.error(f"Error performing EEAT assessment: {str(e)}", exc_info=True)
        raise HTTPException(
            status_code=500,
            detail=f"Internal server error: {str(e)}"
        )

@app.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "timestamp": datetime.utcnow().isoformat()}

# if __name__ == "__main__":
#     import uvicorn
#     uvicorn.run(app, host="0.0.0.0", port=8888)

