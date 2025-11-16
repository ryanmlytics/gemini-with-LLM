# Agent-Will-Smith API Server

Python FastAPI server that replaces the Vext API with Google Gemini backend. Maintains full compatibility with existing Laravel client code.

**Model**: Gemini 2.5 Flash Lite ($0.1/$0.4 per 1M tokens) - Cost-optimized choice vs Vext ($1/$1)

## Features

- **Three Core Endpoints**: `POST /generateQuestions`, `POST /getMetadata`, `POST /getAnswer`
- **Gemini Integration**: Uses Google Gemini for LLM operations
- **Multi-Language Support**: Generate questions and answers in multiple languages via optional `lang` parameter
- **Caching**: Multi-tier caching (Redis + file fallback)
- **Streaming**: Server-Sent Events (SSE) support for answers
- **API Compatibility**: Maintains exact request/response format from Vext API

## Prerequisites

- Python 3.11+ (3.11/3.12 recommended)
- **Google Gemini API key** (REQUIRED) - [Get one here](https://ai.google.dev/)
- Redis (optional - file cache used as fallback)

## Quick Start

### 1. Install Dependencies

```bash
pip install -r requirements.txt
```

**For Python 3.13:** If you encounter Rust errors, use:
```bash
pip install --only-binary :all: -r requirements.txt
pip install --only-binary :all: lxml
```

### 2. Configure Environment

Create `.env` file:
```env
GEMINI_API_KEY=your_gemini_api_key_here
# Required in protected environments
API_BEARER_TOKEN=change_me
ALLOWED_ORIGINS=https://your-allowed-origin.com
# Optional
GEMINI_MODEL=gemini-2.5-flash-lite  # Cost: $0.1/$0.4 per 1M tokens (input/output)
REDIS_URL=redis://localhost:6379/0
```

### 3. Run the Server

```bash
python run.py
```

Server starts on `http://localhost:8888`

### 4. Test

#### Quick Health Check
```bash
curl http://localhost:8888/health
```

#### Generate Questions (with URL)
```bash
curl -X POST http://localhost:8888/generateQuestions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer change_me" \
  -d '{
    "inputs": {
      "url": "https://m.cnyes.com/news/id/5627491",
      "lang": "zh-tw"
    },
    "user": "test_user",
    "type": "answer_page"
  }'
```

#### Generate Questions (with Context - Widget Page)
```bash
curl -X POST http://localhost:8888/generateQuestions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer change_me" \
  -d '{
    "inputs": {
      "url": "",
      "context": "A股港股《異動股》天泓文創(08500)升逾40%,現報0.75元...",
      "prompt": "# 角色 你是鉅亨網（Cnyes.com）的資深金融新聞記者，擅長以市場節奏與專業語氣撰寫能引起投資人關注的「提問式標題」。\n# 任務 根據提供的文章，生成一個「標題式提問」。",
      "lang": "zh-tw"
    },
    "user": "86b51fd1-5186-45c2-84f6-7977dd616119",
    "type": "widget_page",
    "source_url": "https://m.cnyes.com/news/id/5627491"
  }'
```

#### Get Metadata (with Domain Filtering)
```bash
curl -X POST http://localhost:8888/getMetadata \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer change_me" \
  -d '{
    "inputs": {
      "url": "https://m.cnyes.com/news/id/5627491",
      "query": "天泓文創 股票 異動",
      "tag_prompt": "Generate 5 concise topic tags"
    },
    "user": "test_user"
  }'
```

#### Get Answer (with URL)
```bash
curl -X POST http://localhost:8888/getAnswer \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer change_me" \
  -d '{
    "inputs": {
      "query": "天泓文創股價為何飆升？",
      "url": "https://m.cnyes.com/news/id/5627491",
      "lang": "zh-tw"
    },
    "user": "test_user",
    "stream": false
  }'
```

#### Get Answer (with Content ID - Session)
```bash
# First, generate questions to get content_id
# Then use that content_id to get answer
curl -X POST http://localhost:8888/getAnswer \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer change_me" \
  -d '{
    "inputs": {
      "query": "天泓文創股價為何飆升？",
      "content_id": "56e71457-c55d-4b13-bc8a-205cbdb42673",
      "lang": "zh-tw"
    },
    "user": "test_user",
    "stream": false
  }'
```

#### Run Automated Tests
```bash
# Install test dependencies
pip install -r requirements.txt

# Run all tests (uses default test domain: https://m.cnyes.com/news/id/5627491)
pytest tests/ -v

# Run with custom test domain
TEST_DOMAIN=https://your-test-domain.com/article pytest tests/ -v

# Run specific test file
pytest tests/test_output_format.py -v

# Run with coverage
pytest tests/ -v --cov=app --cov=services
```

**Test Configuration:**
- `TEST_DOMAIN`: Test URL for API endpoints (default: `https://m.cnyes.com/news/id/5627491`)
- `TEST_BASE_URL`: Base URL for domain extraction tests (default: `https://m.cnyes.com`)

Set these in your `.env` file or export as environment variables before running tests.

## Configuration

Edit `.env` file:

```env
# Required
GEMINI_API_KEY=your_key_here
API_BEARER_TOKEN=change_me
ALLOWED_ORIGINS=https://your-allowed-origin.com

# Optional
GEMINI_MODEL=gemini-2.5-flash-lite  # Cost: $0.1/$0.4 per 1M tokens (input/output). Alternative: gemini-2.5-flash ($0.3/$2.5)
REDIS_URL=redis://localhost:6379/0
HOST=0.0.0.0
PORT=8888
LOG_LEVEL=INFO

# Google Custom Search (optional - only for related sources)
GOOGLE_SEARCH_KEY=
GOOGLE_SEARCH_ENGINE_ID=

# Test Configuration (optional - for running tests)
TEST_DOMAIN=https://m.cnyes.com/news/id/5627491
TEST_BASE_URL=https://m.cnyes.com
```

## Security

- **Bearer token authentication**: All POST endpoints require `Authorization: Bearer <token>`. Configure the shared secret via `API_BEARER_TOKEN`. When the variable is unset (local development), authentication is skipped but a warning is logged.
- **CORS policy**: Control allowed origins with the comma-separated `ALLOWED_ORIGINS` variable. If omitted, only localhost origins are allowed.
- Store secrets with your deployment platform's secret manager (for example, Cloud Run secrets) and rotate them regularly.

## Go-Live Decisions

**Model Choice**: Gemini 2.5 Flash Lite ($0.1/$0.4 per 1M tokens) - Cost-optimized vs Vext ($1/$1). Databricks AI Gateway kept on roadmap for future A/B testing.

**Authentication**: Bearer token authentication implemented. Firewall setup skipped for Cloud Run (too tedious).

**Scaling**: Cloud Run auto-scaling configured (max 10 instances). Bottleneck expected to be Gemini response latency.

**Observability**: Cloud Run dashboard provides basic metrics and logs. Additional monitoring can be added as needed.

**Testing**: 
- **Automated tests**: Comprehensive unit and API tests covering schema validation, input/output format, URL/context precedence, and content_id session logic. Run with `pytest tests/ -v`
- **Manual testing**: Postman collection available for E2E testing after deployment
- **Human evaluation**: Content quality evaluation by team members

## Laravel Integration

Update `MyLib/MyAPI.php`:

```php
// Change from:
private $api_host = "https://mlytics-api.vextapp.com";

// To:
private $api_host = "https://your-api-server.com";
```

**That's it!** The API contract is identical. All existing Laravel code works without modifications.

## API Endpoints

### POST /generateQuestions

Generate 1-5 questions from content or URL.

**Request:**
```json
{
  "inputs": {
    "url": "https://m.cnyes.com/news/id/5627491",
    "context": "Optional: direct content text",
    "prompt": "Optional: custom prompt for question generation",
    "lang": "zh-tw",
    "previous_questions": ["Optional: list of previous questions"]
  },
  "user": "86b51fd1-5186-45c2-84f6-7977dd616119",
  "type": "widget_page",
  "source_url": "https://m.cnyes.com/news/id/5627491"
}
```

**Response:**
```json
{
  "task_id": "1d779a47-b403-427f-b4b4-9120d9841175",
  "data": {
    "status": "succeeded",
    "outputs": {
      "result": {
        "question_1": "天泓文創(08500)盤中飆升逾40%，創52周新高，背後有何催化劑？",
        "question_2": "天泓文創股價放量創高，市場資金動向透露了什麼訊號？",
        "question_3": "成交量與股價同步走高，這是否意味著天泓文創的上升趨勢將持續？",
        "question_4": "55:45的主動買沽比率，如何解讀市場對天泓文創的看法？",
        "question_5": "RSI飆升至83.58，天泓文創是否已進入超買區間？"
      },
      "content_id": "56e71457-c55d-4b13-bc8a-205cbdb42673"
    },
    "elapsed_time": 1.605955,
    "created_at": 1761248073,
    "finished_at": 1761248075
  }
}
```

**Note:** If both `url` and `context` are provided, `context` takes precedence. Empty string `url: ""` is treated as no URL.

**Language Parameter (`lang`):**
- Optional parameter (defaults to `"zh-tw"` if not specified)
- Controls the language of generated questions
- See [Language Support](#language-support) section for supported language codes

### POST /getMetadata

Extract metadata (title, summary, tags, images) from URL. **Domain filtering:** Search results are automatically filtered to only include items from the same domain as the input URL.

**Request:**
```json
{
  "inputs": {
    "url": "https://m.cnyes.com/news/id/5627491",
    "query": "天泓文創 股票 異動",
    "tag_prompt": "Generate 5 concise topic tags"
  },
  "user": "test_user"
}
```

**Response:**
```json
{
  "task_id": "1f802502-0c9c-4733-87fb-0a2499af6cbb",
  "data": {
    "status": "succeeded",
    "outputs": {
      "tag": "港股, 異動股, 天泓文創, 股票, 金融",
      "images": [
        {
          "images": "{\n  \"images\": []\n}"
        }
      ],
      "sources": [
        {
          "sources": "{\n  \"citations\": [\n    {\n      \"title\": \"相關文章標題\",\n      \"url\": \"https://cnyes.com/related-article\",\n      \"content\": \"相關文章摘要...\"\n    }\n  ]\n}"
        }
      ]
    },
    "elapsed_time": 2.41,
    "created_at": 1761245271,
    "finished_at": 1761245273
  }
}
```

**Note:** Domain is normalized (e.g., `m.cnyes.com` → `cnyes.com`). All sources are filtered to match the extracted domain.

### POST /getAnswer

Generate answer with optional SSE streaming. Can use `content_id` from `/generateQuestions` to retrieve previously saved content.

**Request:**
```json
{
  "inputs": {
    "query": "天泓文創股價為何飆升？",
    "url": "https://m.cnyes.com/news/id/5627491",
    "content_id": "56e71457-c55d-4b13-bc8a-205cbdb42673",
    "prompt": "Optional: custom prompt",
    "lang": "zh-tw"
  },
  "user": "test_user",
  "stream": false
}
```

**Response (non-streaming):**
```json
{
  "event": "workflow_finished",
  "task_id": "9737ff45-e015-4e2d-8505-c7525a655d50",
  "data": {
    "status": "succeeded",
    "outputs": {
      "result": "Generated answer text..."
    },
    "elapsed_time": 3.709378,
    "created_at": 1761248666,
    "finished_at": 1761248670
  }
}
```

**Note:** If `content_id` is provided, it retrieves content saved during `/generateQuestions`. Otherwise, it fetches from `url`. Set `"stream": true` for SSE streaming.

**Language Parameter (`lang`):**
- Optional parameter (defaults to `"zh-tw"` if not specified)
- Controls the language of generated answers
- Works for both streaming and non-streaming responses
- See [Language Support](#language-support) section for supported language codes

## Language Support

The API supports generating questions and answers in multiple languages through the optional `lang` parameter in both `/generateQuestions` and `/getAnswer` endpoints.

### Supported Language Codes

| Code | Language | Native Name |
|------|----------|-------------|
| `en` | English | English |
| `zh-tw` | Traditional Chinese | 繁體中文 (default) |
| `zh-cn` | Simplified Chinese | 简体中文 |
| `zh` | Chinese (generic) | 中文 |
| `es` | Spanish | Español |
| `fr` | French | Français |
| `de` | German | Deutsch |
| `it` | Italian | Italiano |
| `pt` | Portuguese | Português |
| `ja` | Japanese | 日本語 |
| `ko` | Korean | 한국어 |
| `ru` | Russian | Русский |
| `ar` | Arabic | العربية |
| `hi` | Hindi | हिन्दी |
| `th` | Thai | ไทย |
| `vi` | Vietnamese | Tiếng Việt |
| `id` | Indonesian | Bahasa Indonesia |
| `nl` | Dutch | Nederlands |
| `pl` | Polish | Polski |
| `tr` | Turkish | Türkçe |

### Usage Examples

#### Generate Questions in English
```bash
curl -X POST http://localhost:8888/generateQuestions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer change_me" \
  -d '{
    "inputs": {
      "url": "https://example.com/article",
      "lang": "en"
    },
    "user": "test_user",
    "type": "answer_page"
  }'
```

#### Generate Questions in Japanese
```bash
curl -X POST http://localhost:8888/generateQuestions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer change_me" \
  -d '{
    "inputs": {
      "url": "https://example.com/article",
      "lang": "ja"
    },
    "user": "test_user",
    "type": "answer_page"
  }'
```

#### Get Answer in Spanish
```bash
curl -X POST http://localhost:8888/getAnswer \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer change_me" \
  -d '{
    "inputs": {
      "query": "What are the key benefits?",
      "url": "https://example.com/article",
      "lang": "es"
    },
    "user": "test_user",
    "stream": false
  }'
```

**Note:** If the `lang` parameter is omitted, the API defaults to `"zh-tw"` (Traditional Chinese). The language code is case-insensitive and will be normalized automatically.

## Caching

- **Redis** (primary) - Fast in-memory cache
- **File system** (fallback) - Automatic when Redis unavailable

**Setup Redis (Optional):**
```bash
docker run -d -p 6379:6379 --name redis redis:latest
```

Add to `.env`: `REDIS_URL=redis://localhost:6379/0`

## Deployment

**Development:**
```bash
python run.py
```

**Production:**
```bash
uvicorn app:app --host 0.0.0.0 --port 8888 --workers 4
```

**Docker:**
```bash
docker build -t aigc-api-server .
docker run -p 8888:8888 --env-file .env aigc-api-server
```



## Troubleshooting

### Installation Issues

- **Python 3.13 Rust errors**: Use pre-built wheels (see Quick Start) or use Python 3.11/3.12
- **Missing modules**: `pip install --upgrade pip && pip install -r requirements.txt`

### Connection Issues

- **API key invalid**: Check `.env` file contains correct `GEMINI_API_KEY`
- **Connection timeout**: Check firewall, VPN, or network restrictions
- **Redis not working**: File cache will be used automatically (no action needed)

### Server Issues

- **Port in use**: Change `PORT` in `.env` or kill process using port 8888
- **Import errors**: Verify all dependencies installed: `pip install -r requirements.txt`

## Project Structure

```
app.py                    # FastAPI main application
├── services/
│   ├── gemini_service.py    # Gemini API integration
│   ├── search_service.py    # Google Search & web scraping
│   ├── cache_service.py     # Redis/file caching
│   └── content_service.py   # Content fetching
└── requirements.txt         # Python dependencies
```

## License

MIT
