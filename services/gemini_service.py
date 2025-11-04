"""
Gemini Service - Handles Google Gemini API integration
"""

import os
import asyncio
import logging
from typing import List, Dict, Any, Optional, AsyncGenerator
from tenacity import retry, stop_after_attempt, wait_exponential

import google.generativeai as genai
from google.generativeai.types import HarmCategory, HarmBlockThreshold
from google.api_core import exceptions as google_exceptions

logger = logging.getLogger(__name__)


class GeminiService:
    """Service for interacting with Google Gemini API"""
    
    def __init__(self):
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEY environment variable is required")
        
        genai.configure(api_key=api_key)
        self.model_name = os.getenv("GEMINI_MODEL", "gemini-1.5-flash")
        self.model = genai.GenerativeModel(self.model_name)
        
        # Safety settings
        self.safety_settings = {
            HarmCategory.HARM_CATEGORY_HATE_SPEECH: HarmBlockThreshold.BLOCK_MEDIUM_AND_ABOVE,
            HarmCategory.HARM_CATEGORY_HARASSMENT: HarmBlockThreshold.BLOCK_MEDIUM_AND_ABOVE,
            HarmCategory.HARM_CATEGORY_SEXUALLY_EXPLICIT: HarmBlockThreshold.BLOCK_MEDIUM_AND_ABOVE,
            HarmCategory.HARM_CATEGORY_DANGEROUS_CONTENT: HarmBlockThreshold.BLOCK_MEDIUM_AND_ABOVE,
        }
        
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10)
    )
    async def generate_questions(
        self,
        content: str,
        lang: str = "zh-tw",
        max_questions: int = 5,
        previous_questions: Optional[List[str]] = None,
        custom_prompt: Optional[str] = None
    ) -> Dict[str, Any]:
        """
        Generate questions from content
        
        Args:
            content: Article/content text
            lang: Language code (e.g., zh-tw, en)
            max_questions: Maximum number of questions to generate
            previous_questions: List of existing questions to avoid duplicates
            
        Returns:
            Dict with questions list and metadata
        """
        previous = previous_questions or []
        
        # Build prompt
        lang_prompt = "繁體中文" if lang == "zh-tw" else "English"
        
        # Build prompt - use custom prompt if provided, otherwise use default
        if custom_prompt and custom_prompt.strip():
            # Use custom prompt as the main instruction
            base_instruction = custom_prompt.strip()
            # Add requirements for short questions if custom prompt is used
            requirements = f"""Requirements:
1. Follow the instruction: {base_instruction}
2. Generate {max_questions} questions in {lang_prompt}
3. Keep questions short and simple (under 20 words for Chinese, under 15 words for English)
4. Return JSON format: {{"questions": [{{"id": "q1", "text": "Question text", "type": "fact|analysis|exploratory", "confidence": 0.0-1.0}}]}}"""
        else:
            # Default: Generate short, simple, direct questions (similar to Vext style)
            base_instruction = f"Generate {max_questions} short, simple, direct questions in {lang_prompt}"
            requirements = f"""Requirements:
1. Questions must be short and simple (like: \"什麼是包冰？\" or \"Why does frozen shrimp have ice?\")
2. Each question should be direct and easy to understand
3. Avoid long, complex questions
4. Return JSON format: {{"questions": [{{"id": "q1", "text": "Question text", "type": "fact|analysis|exploratory", "confidence": 0.0-1.0}}]}}"""
        
        prompt = f"""{base_instruction}

Content:
{content[:5000]}

{requirements}

{f'Previous questions to avoid: {", ".join(previous)}' if previous else ''}

Generate questions now:"""
        
        try:
            # Run synchronous Gemini API call in thread pool
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                lambda: self.model.generate_content(
                    prompt,
                    safety_settings=self.safety_settings
                )
            )
            
            # Parse response
            result_text = response.text
            
            # Try to extract JSON from response
            import json
            import re
            
            # Find JSON in response
            json_match = re.search(r'\{.*\}', result_text, re.DOTALL)
            if json_match:
                result_data = json.loads(json_match.group())
            else:
                # Fallback: create questions from text
                questions_text = result_text.split('\n')
                result_data = {
                    "questions": [
                        {
                            "id": f"q{i+1}",
                            "text": q.strip(),
                            "type": "analytical",
                            "confidence": 0.85
                        }
                        for i, q in enumerate(questions_text[:max_questions])
                        if q.strip() and not q.strip().startswith('#')
                    ]
                }
            
            # Limit to max_questions
            if len(result_data.get("questions", [])) > max_questions:
                result_data["questions"] = result_data["questions"][:max_questions]
            
            return {
                "questions": result_data.get("questions", []),
                "tokens_used": response.usage_metadata.total_token_count if hasattr(response, 'usage_metadata') else 0,
                "content_id": None  # Can be set by caller
            }
            
        except google_exceptions.FailedPrecondition as e:
            error_msg = str(e)
            if "location is not supported" in error_msg.lower():
                logger.warning("Gemini API not available in this region. Location restriction detected.")
                raise ValueError("Gemini API is not available in your region. Please use VPN or deploy to a supported region (USA/Europe).")
            raise
        except (google_exceptions.ServiceUnavailable, google_exceptions.RetryError) as e:
            error_msg = str(e)
            if "timeout" in error_msg.lower() or "connection timed out" in error_msg.lower() or "failed to connect" in error_msg.lower():
                logger.error(f"Connection timeout to Gemini API: {error_msg}")
                raise ValueError("Cannot connect to Gemini API. Please check your network connection, firewall settings, or use VPN if Google services are blocked in your region.")
            raise
        except Exception as e:
            logger.error(f"Error generating questions: {str(e)}", exc_info=True)
            raise
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10)
    )
    async def generate_answer(
        self,
        content: str,
        question: str,
        prompt: Optional[str] = None,
        lang: str = "zh-tw",
        max_tokens: int = 800
    ) -> Dict[str, Any]:
        """
        Generate answer to question based on content
        
        Args:
            content: Source content
            question: User question
            prompt: Optional custom prompt
            lang: Language code
            max_tokens: Maximum tokens in response
            
        Returns:
            Dict with answer text and metadata
        """
        lang_prompt = "繁體中文" if lang == "zh-tw" else "English"
        
        base_prompt = prompt or f"""Based on the provided content, answer the question comprehensively in {lang_prompt}.

Content:
{content[:10000]}  # Limit content length

Question: {question}

Requirements:
1. Provide a clear, analytical answer
2. Cite specific parts of the content when relevant
3. If the content doesn't contain enough information, state that clearly
4. Format response in clear paragraphs
5. Use markdown for formatting if needed

Answer:"""
        
        try:
            # Run synchronous Gemini API call in thread pool
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                lambda: self.model.generate_content(
                    base_prompt,
                    safety_settings=self.safety_settings,
                    generation_config={
                        "max_output_tokens": max_tokens,
                        "temperature": 0.7,
                    }
                )
            )
            
            answer = response.text
            
            return {
                "answer": answer,
                "tokens_used": response.usage_metadata.total_token_count if hasattr(response, 'usage_metadata') else 0
            }
            
        except google_exceptions.FailedPrecondition as e:
            error_msg = str(e)
            if "location is not supported" in error_msg.lower():
                logger.warning("Gemini API not available in this region. Location restriction detected.")
                raise ValueError("Gemini API is not available in your region. Please use VPN or deploy to a supported region (USA/Europe).")
            raise
        except (google_exceptions.ServiceUnavailable, google_exceptions.RetryError) as e:
            error_msg = str(e)
            if "timeout" in error_msg.lower() or "connection timed out" in error_msg.lower() or "failed to connect" in error_msg.lower():
                logger.error(f"Connection timeout to Gemini API: {error_msg}")
                raise ValueError("Cannot connect to Gemini API. Please check your network connection, firewall settings, or use VPN if Google services are blocked in your region.")
            raise
        except Exception as e:
            logger.error(f"Error generating answer: {str(e)}", exc_info=True)
            raise
    
    async def stream_answer(
        self,
        content: str,
        question: str,
        prompt: Optional[str] = None,
        lang: str = "zh-tw"
    ) -> AsyncGenerator[str, None]:
        """
        Stream answer chunks from Gemini
        
        Args:
            content: Source content
            question: User question
            prompt: Optional custom prompt
            lang: Language code
            
        Yields:
            String chunks of the answer
        """
        lang_prompt = "繁體中文" if lang == "zh-tw" else "English"
        
        base_prompt = prompt or f"""Based on the provided content, answer the question comprehensively in {lang_prompt}.

Content:
{content[:10000]}

Question: {question}

Answer:"""
        
        try:
            # For streaming, we need to process chunks as they come
            # Create a queue to pass chunks from sync to async
            chunk_queue = asyncio.Queue()
            
            def generate_stream():
                try:
                    response = self.model.generate_content(
                        base_prompt,
                        safety_settings=self.safety_settings,
                        stream=True
                    )
                    for chunk in response:
                        if chunk.text:
                            chunk_queue.put_nowait(chunk.text)
                    chunk_queue.put_nowait(None)  # Signal end
                except Exception as e:
                    chunk_queue.put_nowait(StopIteration)
                    logger.error(f"Stream generation error: {str(e)}")
            
            # Start generation in background thread
            loop = asyncio.get_event_loop()
            loop.run_in_executor(None, generate_stream)
            
            # Yield chunks as they arrive
            while True:
                chunk = await chunk_queue.get()
                if chunk is None or chunk is StopIteration:
                    break
                yield chunk
                    
        except Exception as e:
            logger.error(f"Error streaming answer: {str(e)}", exc_info=True)
            raise
    
    async def extract_citations(
        self,
        answer: str,
        sources: List[Dict[str, Any]]
    ) -> List[Dict[str, Any]]:
        """
        Extract citations from answer text
        
        Args:
            answer: Answer text
            sources: List of source dictionaries
            
        Returns:
            List of citation dictionaries
        """
        # Simple citation extraction
        # Can be enhanced with more sophisticated parsing
        citations = []
        
        # Look for URL patterns or source references
        import re
        url_pattern = r'https?://[^\s\)]+'
        urls = re.findall(url_pattern, answer)
        
        for url in urls:
            citations.append({
                "url": url,
                "text": "",  # Can be extracted from context
                "span": ""
            })
        
        return citations
    
    async def generate_tags(
        self,
        content: str,
        tag_prompt: Optional[str] = None
    ) -> List[str]:
        """
        Generate tags from content
        
        Args:
            content: Content text
            tag_prompt: Custom prompt for tag generation
            
        Returns:
            List of tag strings
        """
        prompt = tag_prompt or f"""Generate 5 concise topic tags for the following content. 
Return only a comma-separated list of tags, no explanation.

Content:
{content[:3000]}

Tags:"""
        
        try:
            # Run synchronous Gemini API call in thread pool
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                lambda: self.model.generate_content(
                    prompt,
                    safety_settings=self.safety_settings
                )
            )
            
            tags_text = response.text.strip()
            tags = [tag.strip() for tag in tags_text.split(',') if tag.strip()]
            
            return tags[:5]  # Limit to 5 tags
            
        except Exception as e:
            logger.error(f"Error generating tags: {str(e)}", exc_info=True)
            return []

