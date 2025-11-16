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


def get_language_name(lang_code: str) -> str:
    """
    Convert language code to native language name for prompts.
    Supports common language codes.
    
    Args:
        lang_code: Language code (e.g., 'en', 'zh-tw', 'es', 'fr', etc.)
        
    Returns:
        Native language name for use in prompts
    """
    lang_map = {
        "en": "English",
        "zh-tw": "繁體中文",
        "zh-cn": "简体中文",
        "zh": "中文",
        "es": "Español",
        "fr": "Français",
        "de": "Deutsch",
        "it": "Italiano",
        "pt": "Português",
        "ja": "日本語",
        "ko": "한국어",
        "ru": "Русский",
        "ar": "العربية",
        "hi": "हिन्दी",
        "th": "ไทย",
        "vi": "Tiếng Việt",
        "id": "Bahasa Indonesia",
        "nl": "Nederlands",
        "pl": "Polski",
        "tr": "Türkçe",
    }
    
    # Normalize language code (lowercase, handle variations)
    lang_code = lang_code.lower().strip()
    
    # Return mapped language or use the code itself if not found
    return lang_map.get(lang_code, lang_code.upper())


class GeminiService:
    """Service for interacting with Google Gemini API"""
    
    def __init__(self):
        api_key = os.getenv("GEMINI_API_KEY")
        if not api_key:
            raise ValueError("GEMINI_API_KEY environment variable is required")
        
        genai.configure(api_key=api_key)
        self.model_name = os.getenv("GEMINI_MODEL", "gemini-2.5-flash-lite")
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
        
        # Build prompt with language support
        lang_prompt = get_language_name(lang or "zh-tw")
        
        # Build prompt - use custom prompt if provided, otherwise use default
        if custom_prompt and custom_prompt.strip():
            # Use custom prompt as the PRIMARY instruction (like Vext does)
            # Let the custom prompt fully control the style - no extra constraints
            prompt = f"""{custom_prompt.strip()}

Content:
{content[:5000]}

Generate {max_questions} questions in {lang_prompt}.

{f'Previous questions to avoid: {", ".join(previous)}' if previous else ''}

Return JSON format: {{"questions": [{{"id": "q1", "text": "Question text", "type": "fact|analysis|exploratory", "confidence": 0.0-1.0}}]}}"""
        else:
            # Default: Generate short, simple, direct questions (similar to Vext style)
            prompt = f"""Generate {max_questions} short, simple, direct questions in {lang_prompt}.

Content:
{content[:5000]}

Requirements:
1. Questions must be short and simple (like: \"什麼是包冰？\" or \"Why does frozen shrimp have ice?\")
2. Each question should be direct and easy to understand
3. Avoid long, complex questions
4. Keep questions concise (under 20 words for Chinese, under 15 words for English)

{f'Previous questions to avoid: {", ".join(previous)}' if previous else ''}

Return JSON format: {{"questions": [{{"id": "q1", "text": "Question text", "type": "fact|analysis|exploratory", "confidence": 0.0-1.0}}]}}"""
        
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
        lang_prompt = get_language_name(lang or "zh-tw")
        
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
        lang_prompt = get_language_name(lang or "zh-tw")
        
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
    
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=10)
    )
    async def assess_eeat(
        self,
        content: str,
        metadata: Optional[Dict[str, Any]] = None,
        lang: str = "en"
    ) -> Dict[str, Any]:
        """
        Assess E-E-A-T (Experience, Expertise, Authoritativeness, Trust) quality of content
        
        Args:
            content: Content text to assess
            metadata: Optional metadata (author, publish_date, topic_category)
            lang: Language code for response
            
        Returns:
            Dict with E-E-A-T scores and rationale
        """
        lang_prompt = get_language_name(lang or "en")
        
        # Build metadata context
        metadata_context = ""
        if metadata:
            if metadata.get("author"):
                metadata_context += f"Author: {metadata['author']}\n"
            if metadata.get("publish_date"):
                metadata_context += f"Publish Date: {metadata['publish_date']}\n"
            if metadata.get("topic_category"):
                metadata_context += f"Topic Category: {metadata['topic_category']}\n"
        
        prompt = f"""You are an expert content quality assessor following Google's Search Quality Rater Guidelines. 
Analyze the following content and assess its E-E-A-T (Experience, Expertise, Authoritativeness, Trust) quality.

Content to analyze:
{content[:15000]}

{metadata_context if metadata_context else ''}

Assessment Requirements:
1. Evaluate each E-E-A-T component independently
2. For Experience: Assess if content shows first-hand or life experience relevant to the topic
3. For Expertise: Assess if content demonstrates necessary knowledge or skill for the topic
4. For Authoritativeness: Assess if the source is recognized as authoritative in the field
5. For Trust: Assess if content is accurate, transparent, and safe (THIS IS CRITICAL - if trust fails, overall rating must be Lowest)

Level Definitions:
- Experience: High | Adequate | Lacking | N/A
- Expertise: High | Adequate | Lacking | N/A
- Authoritativeness: Very High | High | Adequate | Lacking | N/A
- Trust: Trustworthy | Adequate | Untrustworthy

Overall Page Quality: Highest | High | Medium | Low | Lowest

YMYL (Your Money or Your Life) Check: true | false

Return your assessment in JSON format with this exact structure:
{{
  "overall_level": "High E-E-A-T",
  "scores": {{
    "experience": {{
      "level": "High|Adequate|Lacking|N/A",
      "confidence": 0.0-1.0,
      "rationale": ["bullet point 1", "bullet point 2", "bullet point 3"]
    }},
    "expertise": {{
      "level": "High|Adequate|Lacking|N/A",
      "confidence": 0.0-1.0,
      "rationale": ["bullet point 1", "bullet point 2", "bullet point 3"]
    }},
    "authoritativeness": {{
      "level": "Very High|High|Adequate|Lacking|N/A",
      "confidence": 0.0-1.0,
      "rationale": ["bullet point 1", "bullet point 2", "bullet point 3"]
    }},
    "trust": {{
      "level": "Trustworthy|Adequate|Untrustworthy",
      "confidence": 0.0-1.0,
      "rationale": ["bullet point 1", "bullet point 2", "bullet point 3"]
    }}
  }},
  "page_quality_rating": "Highest|High|Medium|Low|Lowest",
  "is_ymyl": true|false,
  "evidence_summary": {{
    "on_page": ["evidence 1", "evidence 2"],
    "external": ["evidence 1", "evidence 2"]
  }},
  "recommendations": ["recommendation 1", "recommendation 2"]
}}

IMPORTANT: 
- If trust level is "Untrustworthy", overall_level must be "Lowest E-E-A-T" and page_quality_rating must be "Lowest"
- Provide 3-5 bullet points for each rationale
- Confidence scores should reflect how certain you are about the assessment
- Be specific and evidence-based in your rationale

Respond in {lang_prompt} for rationale and recommendations, but keep level values in English as specified above."""
        
        try:
            # Run synchronous Gemini API call in thread pool
            loop = asyncio.get_event_loop()
            response = await loop.run_in_executor(
                None,
                lambda: self.model.generate_content(
                    prompt,
                    safety_settings=self.safety_settings,
                    generation_config={
                        "max_output_tokens": 2000,
                        "temperature": 0.3,  # Lower temperature for more consistent assessments
                    }
                )
            )
            
            result_text = response.text
            
            # Parse JSON from response
            import json
            import re
            
            # Find JSON in response
            json_match = re.search(r'\{.*\}', result_text, re.DOTALL)
            if json_match:
                result_data = json.loads(json_match.group())
            else:
                # Fallback: try to parse the entire response
                try:
                    result_data = json.loads(result_text)
                except:
                    logger.error(f"Failed to parse EEAT assessment JSON: {result_text[:500]}")
                    raise ValueError("Failed to parse EEAT assessment response")
            
            # Validate and normalize the response structure
            return self._normalize_eeat_response(result_data)
            
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
            logger.error(f"Error assessing EEAT: {str(e)}", exc_info=True)
            raise
    
    def _normalize_eeat_response(self, data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Normalize and validate EEAT assessment response
        
        Args:
            data: Raw response data from LLM
            
        Returns:
            Normalized response structure
        """
        # Ensure all required fields exist with defaults
        normalized = {
            "overall_level": data.get("overall_level", "Medium E-E-A-T"),
            "scores": {},
            "page_quality_rating": data.get("page_quality_rating", "Medium"),
            "is_ymyl": data.get("is_ymyl", False),
            "evidence_summary": {
                "on_page": data.get("evidence_summary", {}).get("on_page", []),
                "external": data.get("evidence_summary", {}).get("external", [])
            },
            "recommendations": data.get("recommendations", [])
        }
        
        # Normalize each E-E-A-T component
        scores = data.get("scores", {})
        for component in ["experience", "expertise", "authoritativeness", "trust"]:
            component_data = scores.get(component, {})
            normalized["scores"][component] = {
                "level": component_data.get("level", "N/A"),
                "confidence": float(component_data.get("confidence", 0.5)),
                "rationale": component_data.get("rationale", [])
            }
        
        # Enforce trust gating: if trust is Untrustworthy, set overall to Lowest
        if normalized["scores"]["trust"]["level"] == "Untrustworthy":
            normalized["overall_level"] = "Lowest E-E-A-T"
            normalized["page_quality_rating"] = "Lowest"
        
        return normalized

