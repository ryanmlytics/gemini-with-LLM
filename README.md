# AIGC MVP API Server

Python FastAPI server that replaces the Vext API with Google Gemini backend. Maintains full compatibility with existing Laravel client code.

## Features

- **Three Core Endpoints**: 
  - `POST /generateQuestions` - Generate questions from content
  - `POST /getMetadata` - Extract metadata from URLs
  - `POST /getAnswer` - Generate answers with SSE streaming support

- **Gemini Integration**: Uses Google Gemini 2.0 Flash for LLM operations
- **Caching**: Multi-tier caching (Redis + file fallback)
- **Streaming**: Server-Sent Events (SSE) support for answer generation
- **Error Handling**: Robust error handling with retry logic
- **API Compatibility**: Maintains exact request/response format from Vext API

## Prerequisites

- Python 3.11, 3.12, or 3.13 (3.11/3.12 recommended)
- **Google Gemini API key** (REQUIRED) - [Get one here](https://ai.google.dev/)
- **Redis** (optional, for caching - file cache used as fallback)
- **Google Custom Search API** (optional, only for related source search - images, title, summary come from scraping the URL directly, not from Google Search)

## Quick Start

### 1. Install Dependencies

**For Python 3.11/3.12:**
```bash
pip install -r requirements.txt
```

**For Python 3.13:**
If you encounter Rust compilation errors, use pre-built wheels:
```bash
pip install --only-binary :all: -r requirements.txt
pip install --only-binary :all: lxml
```

### 2. Configure Environment

Copy the example environment file and add your API keys:

```bash
cp .env.example .env
```

Edit `.env` and add your Gemini API key (minimum required):

```env
GEMINI_API_KEY=your_gemini_api_key_here
# Optional: Change model for cost optimization
# GEMINI_MODEL=gemini-1.5-flash-lite  # Cheapest for testing
# GEMINI_MODEL=gemini-1.5-flash      # Recommended (default)
```

See [Configuration](#configuration) section for all available options.

### 3. Run the Server

**Using the run script (recommended):**
```bash
python run.py
```

**Or using uvicorn directly:**
```bash
uvicorn app:app --host 0.0.0.0 --port 8888 --reload
```

The server will start on `http://localhost:8888`

### 4. Test the Server

**Health Check:**
```bash
curl http://localhost:8888/health
```

**Test Endpoints:**

**1. Generate Questions (from URL):**
```bash
curl -X POST http://localhost:8888/generateQuestions \
  -H "Content-Type: application/json" \
  -d '{"inputs": {"url": "https://ai.mlyticsaigc.com/", "lang": "zh-tw"}, "user": "test_user", "type": "answer_page"}'
```

**2. Generate Questions (from context text):**
```bash
curl -X POST http://localhost:8888/generateQuestions \
  -H "Content-Type: application/json" \
  -d '{"inputs": {"context": "This is a sample article about artificial intelligence and machine learning.", "lang": "en"}, "user": "test_user"}'
```

**3. Get Metadata:**
```bash
curl -X POST http://localhost:8888/getMetadata \
  -H "Content-Type: application/json" \
  -d '{"inputs": {"url": "https://ai.mlyticsaigc.com/", "query": "What is this article about?", "tag_prompt": "Generate 5 tags"}, "user": "test_user"}'
```

**4. Get Answer (non-streaming):**
```bash
curl -X POST http://localhost:8888/getAnswer \
  -H "Content-Type: application/json" \
  -d '{"inputs": {"query": "What is this article about?", "url": "https://ai.mlyticsaigc.com/", "lang": "zh-tw"}, "user": "test_user", "stream": false}'
```

**5. Get Answer (streaming - SSE):**
```bash
curl -X POST http://localhost:8888/getAnswer \
  -H "Content-Type: application/json" \
  -N -H "Accept: text/event-stream" \
  -d '{"inputs": {"query": "What is this article about?", "url": "https://ai.mlyticsaigc.com/", "lang": "zh-tw"}, "user": "test_user", "stream": true}'
```

**Windows PowerShell (single-line versions):**
```powershell
# Health check
curl http://localhost:8888/health

# Generate Questions
curl -X POST http://localhost:8888/generateQuestions -H "Content-Type: application/json" -d "{\"inputs\": {\"url\": \"https://ai.mlyticsaigc.com/\", \"lang\": \"zh-tw\"}, \"user\": \"test_user\"}"

# Get Metadata
curl -X POST http://localhost:8888/getMetadata -H "Content-Type: application/json" -d "{\"inputs\": {\"url\": \"https://ai.mlyticsaigc.com/\"}, \"user\": \"test_user\"}"

# Get Answer
curl -X POST http://localhost:8888/getAnswer -H "Content-Type: application/json" -d "{\"inputs\": {\"query\": \"What is this article about?\", \"url\": \"https://ai.mlyticsaigc.com/\", \"lang\": \"zh-tw\"}, \"user\": \"test_user\", \"stream\": false}"
```

**For production server (replace with your URL):**
```bash
# Replace https://your-api-server.com with your actual server URL
curl -X POST https://your-api-server.com/generateQuestions \
  -H "Content-Type: application/json" \
  -d '{"inputs": {"url": "https://example.com/article", "lang": "zh-tw"}, "user": "test_user"}'
```

## Configuration

Edit `.env` file with your settings:

### Required Configuration

```env
# Google Gemini API Key (REQUIRED)
GEMINI_API_KEY=your_gemini_api_key_here

# Gemini model to use (optional, defaults to gemini-1.5-flash)
# Recommended options:
#   - gemini-1.5-flash-lite: Cheapest, fastest, good for testing (~$0.06 per 1000 requests)
#   - gemini-1.5-flash: Best balance, recommended for production (~$0.09 per 1000 requests)
#   - gemini-1.5-pro: Most capable, but 10x more expensive (~$1.50 per 1000 requests)
#   - gemini-2.0-flash-exp: Latest experimental model (pricing may vary)
# Note: Google offers free tier with 1,500 requests/day - great for testing!
GEMINI_MODEL=gemini-1.5-flash
```

### Optional Configuration

# Google Custom Search API (OPTIONAL - only for finding related sources in sources[] array)
# NOT REQUIRED - Without these:
#   - Images, title, summary, tags still work (extracted directly from URL's HTML)
#   - Only sources[] array will be empty (related search results)
# Leave empty if you don't need related source search functionality
GOOGLE_SEARCH_KEY=
GOOGLE_SEARCH_ENGINE_ID=

# Redis for caching (optional, file cache used as fallback)
REDIS_URL=redis://localhost:6379/0

# Cache directory for file-based caching
CACHE_DIR=./cache

# Server configuration
HOST=0.0.0.0
PORT=8888

# Logging level (DEBUG, INFO, WARNING, ERROR, CRITICAL)
LOG_LEVEL=INFO
```

See `.env.example` for all available configuration options with descriptions.

## Installation Troubleshooting

### Python 3.13 Rust Compilation Errors

If you see "metadata-generation-failed" or Rust-related errors with Python 3.13:

**Solution 1 (Recommended):** Use pre-built wheels:
```bash
pip install --only-binary :all: -r requirements.txt
pip install --only-binary :all: lxml
```

**Solution 2:** Install Rust from https://rustup.rs/, then install normally

**Solution 3:** Use Python 3.11 or 3.12 instead (easiest option)

### Other Common Issues

- **"No module named 'pydantic'"**: Run `pip install --upgrade pip && pip install -r requirements.txt`
- **lxml installation fails**: Try `pip install --only-binary lxml lxml`
- **Connection refused**: Ensure server is running on the correct port

## Laravel Integration

### Quick Integration

To use this new API server with your Laravel application, simply update the API host in `MyLib/MyAPI.php`:

```php
// Change line 14 from:
private $api_host = "https://mlytics-api.vextapp.com";

// To:
private $api_host = "https://your-api-server.com";  // Your new API server URL
```

**That's it!** No other changes needed. The API contract is identical.

### Environment-Based Configuration (Recommended)

For better flexibility, use environment variables in Laravel:

```php
// In MyAPI.php
private $api_host;

public function __construct($user = "")
{
    $this->api_host = env('AIGC_API_HOST', 'https://mlytics-api.vextapp.com');
    // ... rest of constructor
}
```

Then in Laravel `.env`:
```env
AIGC_API_HOST=https://your-api-server.com
```

### Feature Flag (For Gradual Rollout)

Add a feature flag for safe migration:

```php
// In MyAPI.php
public function __construct($user = "")
{
    if (env('FEATURE_AI_ORCHESTRATOR', false)) {
        $this->api_host = env('AIGC_API_HOST', 'https://your-api-server.com');
    } else {
        $this->api_host = env('VEXT_API_HOST', 'https://mlytics-api.vextapp.com');
    }
    // ... rest of constructor
}
```

### API Contract Compatibility

The new API server maintains 100% compatibility with the existing Vext API:

**Request Format:**
```json
{
  "inputs": {
    // endpoint-specific inputs
  },
  "user": "uuid_user",
  // optional fields
}
```

**Response Format:**
```json
{
  "event": "workflow_finished",
  "data": {
    "outputs": {
      // endpoint-specific outputs
    },
    "provider": "gemini-2.5-flash",
    "meta": {
      "tokens_used": 123,
      "latency_ms": 420,
      "cached": false
    }
  }
}
```

### Laravel Method Mapping

- `$myAPI->get_question(...)` → `POST /generateQuestions`
- `$myAPI->get_meta(...)` → `POST /getMetadata`
- `$myAPI->get_answer(...)` → `POST /getAnswer`

All existing Laravel code will work without modifications.

## API Endpoints

All endpoints match the existing Vext API contract for seamless integration.

### POST /generateQuestions

Generate 1-5 structured questions from content or URL.

**Request:**
```json
{
  "inputs": {
    "url": "https://example.com/article",
    "context": "Optional context text",
    "lang": "zh-tw",
    "previous_questions": []
  },
  "user": "uuid_user",
  "type": "answer_page"
}
```

**Response:**
```json
{
  "event": "workflow_finished",
  "data": {
    "outputs": {
      "result": [
        {"id": "q1", "text": "Question?", "type": "analytical", "confidence": 0.93}
      ]
    },
    "provider": "gemini-2.5-flash-lite",
    "meta": {
      "tokens_used": 123,
      "latency_ms": 420,
      "cached": false
    }
  }
}
```

### POST /getMetadata

Extract metadata from URL (title, summary, sources, tags, images).

**Request:**
```json
{
  "inputs": {
    "url": "https://example.com/article",
    "query": "Optional search query",
    "tag_prompt": "Generate 5 tags"
  },
  "user": "uuid_user"
}
```

**Response:**
```json
{
  "event": "workflow_finished",
  "data": {
    "outputs": {
      "url": "https://example.com/article",
      "domain": "example.com",
      "title": "Article Title",
      "summary": "Summary...",
      "sources": [...],
      "tags": ["AI", "Tech"],
      "images": [...]
    },
    "meta": {
      "tokens_used": 456,
      "latency_ms": 280,
      "cached": true
    }
  }
}
```

### POST /getAnswer

Generate grounded, analytical answer with optional SSE streaming.

**Request (non-stream):**
```json
{
  "inputs": {
    "query": "What is X?",
    "url": "https://example.com/article",
    "prompt": "Custom prompt",
    "lang": "zh-tw"
  },
  "user": "uuid_user",
  "stream": false
}
```

**Request (stream):**
Same as above with `"stream": true`. Response is SSE stream with events:
- `workflow_started`
- `token_chunk`
- `citations`
- `workflow_finished`

**Response (non-stream):**
```json
{
  "event": "workflow_finished",
  "data": {
    "outputs": {
      "result": "Full answer text..."
    },
    "provider": "gemini-2.5-flash",
    "meta": {
      "tokens_used": 712,
      "latency_ms": 1200,
      "cached": false
    }
  }
}
```

## Architecture

```
app.py                    # FastAPI main application
├── services/
│   ├── gemini_service.py    # Gemini API integration
│   ├── search_service.py    # Google Search & web scraping
│   ├── cache_service.py     # Redis/file caching
│   └── content_service.py   # Content fetching
└── requirements.txt         # Python dependencies
```

## Caching

The server implements multi-tier caching:

1. **Redis** (primary) - Fast in-memory cache
2. **File system** (fallback) - When Redis is unavailable

**Cache TTLs:**
- Questions: 10 minutes
- Metadata: 1 hour
- Answers: 5 minutes

### Setting Up Redis (Optional)

Redis is **optional** - the API works fine with file cache. Redis provides faster caching and is recommended for production.

**Option 1: Using Docker (Easiest - Recommended for Windows)**

1. Install Docker Desktop if you haven't already: https://www.docker.com/products/docker-desktop

2. Run Redis container:
```bash
docker run -d -p 6379:6379 --name redis redis:latest
```

3. Verify Redis is running:
```bash
docker ps
```

**Option 2: Using Docker Compose (Already configured)**

If you have `docker-compose.yml` in the project:
```bash
docker-compose up -d redis
```

**Option 3: Local Installation (Windows)**

1. Download Redis for Windows:
   - Option A: Use WSL2 (recommended): Install Redis in WSL2 Ubuntu
   - Option B: Use Memurai (Redis-compatible for Windows): https://www.memurai.com/get-memurai
   - Option C: Use Redis Stack Docker image

2. For WSL2 (recommended):
```bash
# In WSL2 terminal
sudo apt-get update
sudo apt-get install redis-server
sudo service redis-server start
```

**After Installation:**

Add to your `.env` file:
```env
REDIS_URL=redis://localhost:6379/0
```

**Verify Redis is Working:**

Restart your API server and check the logs. You should see:
- `"Redis cache enabled and connected"` (if Redis is running)
- `"Redis not available, using file cache only"` (if Redis is not running - this is fine, file cache works)

**Note:** If Redis is not running, the API will automatically use file cache without errors.

## Deployment

### Development

```bash
python run.py
```

### Production with Uvicorn

```bash
uvicorn app:app --host 0.0.0.0 --port 8888 --workers 4
```

### Docker

**Build and run:**
```bash
docker build -t aigc-api-server .
docker run -p 8888:8888 --env-file .env aigc-api-server
```

**Using Docker Compose:**
```bash
docker-compose up -d
```

### Production Considerations

1. Use environment variables for all secrets
2. Configure proper CORS origins in `app.py`
3. Set up Redis for production caching
4. Use reverse proxy (nginx) for SSL termination
5. Monitor logs and metrics
6. Set up rate limiting
7. Use process manager (systemd, supervisor, etc.)

## Testing

### Quick Test Script

Run the automated test suite:

```bash
# Install requests if not already installed
pip install requests

# Run tests
python test_api.py
```

The test script will:
- Check server health
- Test all three endpoints
- Verify response formats
- Test both streaming and non-streaming modes
- Provide a detailed summary

### Manual Testing with curl

See the [Quick Start - Test the Server](#4-test-the-server) section above for comprehensive curl examples.

**Quick Reference:**

All endpoints are documented with curl examples in the [Quick Start - Test the Server](#4-test-the-server) section above. Here's a quick summary:

- **Health Check:** `curl http://localhost:8888/health`
- **Generate Questions:** See example #1 and #2 above (from URL or context)
- **Get Metadata:** See example #3 above  
- **Get Answer:** See example #4 (non-streaming) and #5 (streaming) above

For detailed examples with real URLs and PowerShell commands, see the Quick Start section above.

### Testing with Python requests

You can also test programmatically:

```python
import requests

# Health check
response = requests.get("http://localhost:8888/health")
print(response.json())

# Generate questions
payload = {
    "inputs": {"url": "https://example.com", "lang": "zh-tw"},
    "user": "test_user"
}
response = requests.post("http://localhost:8888/generateQuestions", json=payload)
print(response.json())
```

### Using Postman or Insomnia

1. Import the endpoints:
   - `GET http://localhost:8888/health`
   - `POST http://localhost:8888/generateQuestions`
   - `POST http://localhost:8888/getMetadata`
   - `POST http://localhost:8888/getAnswer`

2. Set headers:
   - `Content-Type: application/json`

3. Add request bodies (JSON format) as shown in the API Endpoints section above.

## Troubleshooting

### Server won't start

- **Check Python version**: `python --version` (should be 3.11+)
- **Verify dependencies**: `python -c "import fastapi; import google.generativeai; print('OK')"`
- **Check port availability**: Ensure port 8888 is not in use

### API calls failing

- **Verify API key**: Check `.env` file contains valid `GEMINI_API_KEY`
- **Check server logs**: Look for error messages
- **Test health endpoint**: `curl http://localhost:8888/health`

### Slow responses

- **Enable Redis caching**: Add `REDIS_URL` to `.env`
- **Check Gemini API quota**: Verify you haven't exceeded limits
- **Review cache hit rates**: Check logs for cache statistics

### Response format errors

- **Verify API contract**: Ensure request format matches examples
- **Check Laravel integration**: Review `Laravel Integration` section above

### Connection timeout to Gemini API

If you see errors like `Connection timed out` or `failed to connect to all addresses`:

**Symptoms:**
- Error: `503 failed to connect to all addresses; last error: UNAVAILABLE: ipv4:142.250.69.170:443: ConnectEx: Connection timed out`
- Error: `Timeout of 600.0s exceeded`
- Error: `OPENSSL_internal:BAD_DECRYPT` (in Postman)

**Solutions:**

1. **Check network connectivity:**
   ```bash
   # Test if you can reach Google's servers
   ping google.com
   curl -I https://generativelanguage.googleapis.com
   ```

2. **Firewall/Antivirus:**
   - Check if your firewall is blocking outbound connections to port 443
   - Temporarily disable antivirus to test if it's blocking the connection
   - Add Python/your terminal to firewall exceptions

3. **Corporate network/Proxy:**
   - If on corporate network, you may need to configure proxy settings
   - Contact IT to allow outbound connections to `*.googleapis.com`

4. **VPN/Regional restrictions:**
   - Some regions block Google services - use a VPN connected to USA/Europe
   - Verify VPN is working: `curl https://www.google.com`

5. **Windows-specific (Postman SSL error):**
   - The `OPENSSL_internal:BAD_DECRYPT` in Postman is often a network/firewall issue
   - Try disabling SSL verification temporarily in Postman settings (Settings → SSL certificate verification: OFF) - **only for testing**
   - Check Windows Firewall settings

6. **Test connection manually:**
   ```bash
   # Test Gemini API directly
   python -c "import google.generativeai as genai; genai.configure(api_key='YOUR_KEY'); model = genai.GenerativeModel('gemini-1.5-flash'); print(model.generate_content('test').text)"
   ```

**Note:** If connection issues persist, you may need to:
- Deploy the server to a cloud provider (AWS, GCP, Azure) in a supported region
- Use a VPN service
- Contact network administrator if on corporate network

## Error Handling

- Automatic retry with exponential backoff (3 attempts)
- Graceful degradation when services unavailable
- Detailed error logging
- HTTP status codes matching API contract

## License

MIT
