# Agent-Will-Smith API Server

Python FastAPI server that replaces the Vext API with Google Gemini backend. Maintains full compatibility with existing Laravel client code.

**Model**: Gemini 2.5 Flash Lite ($0.1/$0.4 per 1M tokens) - Cost-optimized choice vs Vext ($1/$1)

## Features

- **Three Core Endpoints**: `POST /generateQuestions`, `POST /getMetadata`, `POST /getAnswer`
- **Gemini Integration**: Uses Google Gemini for LLM operations
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

```bash
# Health check
curl http://localhost:8888/health

# Generate questions
curl -X POST http://localhost:8888/generateQuestions \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer change_me" \
  -d '{"inputs": {"url": "https://example.com", "lang": "zh-tw"}, "user": "test_user"}'

# Get metadata
curl -X POST http://localhost:8888/getMetadata \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer change_me" \
  -d '{"inputs": {"url": "https://example.com"}, "user": "test_user"}'

# Get answer
curl -X POST http://localhost:8888/getAnswer \
  -H "Content-Type: application/json" \
  -H "Authorization: Bearer change_me" \
  -d '{"inputs": {"query": "What is this about?", "url": "https://example.com", "lang": "zh-tw"}, "user": "test_user", "stream": false}'
```

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

**Testing**: Basic E2E testing planned with AIGC MVP PHP project. Human evaluation for content quality initially; automated evaluation (AI Agents) planned for future.

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
    "url": "https://example.com/article",
    "lang": "zh-tw"
  },
  "user": "uuid_user"
}
```

### POST /getMetadata

Extract metadata (title, summary, tags, images) from URL.

**Request:**
```json
{
  "inputs": {
    "url": "https://example.com/article"
  },
  "user": "uuid_user"
}
```

### POST /getAnswer

Generate answer with optional SSE streaming.

**Request:**
```json
{
  "inputs": {
    "query": "What is this about?",
    "url": "https://example.com/article",
    "lang": "zh-tw"
  },
  "user": "uuid_user",
  "stream": false
}
```

Set `"stream": true` for SSE streaming.



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
