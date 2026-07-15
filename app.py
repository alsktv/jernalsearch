import os
import json
import logging
from flask import Flask, request, jsonify
from flask_cors import CORS

# Attempt to import the Google Generative AI client
try:
    import google.generativeai as genai
except Exception:
    genai = None

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

app = Flask(__name__)
# Allow CORS from a specific origin if provided, otherwise allow all (use FRONTEND_ORIGIN env var to restrict)
FRONTEND_ORIGIN = os.environ.get("FRONTEND_ORIGIN", "*")
CORS(app, resources={r"/*": {"origins": FRONTEND_ORIGIN}})

# Read Gemini API key from environment
GEMINI_API_KEY = os.environ.get("GEMINI_API_KEY")
DEFAULT_MODEL = os.environ.get("GEMINI_MODEL", "gemini-1.5-flash")

if not GEMINI_API_KEY:
    logger.warning("GEMINI_API_KEY is not set. Gemini calls will fail until the key is provided.")

if genai and GEMINI_API_KEY:
    try:
        # Configure the client
        genai.configure(api_key=GEMINI_API_KEY)
    except Exception as e:
        logger.exception("Failed to configure google.generativeai: %s", e)


SYSTEM_INSTRUCTION = '''
You are a precise research assistant.
Given a user-provided paper title, perform a real-time internet search to find the official metadata for the paper (title, authors, year) and extract at least three real, existing references (works cited by that paper or closely related subsequent works).
Use web search results (do not guess or hallucinate). Ensure each extracted item is an actual existing paper.
Output must be valid JSON ONLY: a JSON array of objects with exactly these keys: title (string), authors (string), year (integer).
Example:
[
  {"title": "Example Paper A", "authors": "Alice, Bob", "year": 2020},
  {"title": "Example Paper B", "authors": "Carol", "year": 2019},
  {"title": "Example Paper C", "authors": "Dan, Eve", "year": 2018}
]
Do not output any markdown or explanatory text. If fewer than three references are found, return whatever you can find but include a "note" field in the error returned by the API explaining limited results.
'''


@app.route('/search', methods=['POST'])
def search_references():
    try:
        if not genai:
            raise RuntimeError("google-generativeai package not available. Install 'google-generativeai'.")
        if not GEMINI_API_KEY:
            raise RuntimeError("GEMINI_API_KEY environment variable is not set.")

        payload = request.get_json(force=True)
        if not payload or 'title' not in payload:
            return jsonify({"error": "Missing 'title' in request body"}), 400

        title = payload['title']
        logger.info("Searching references for title: %s", title)

        # Build a careful prompt that instructs the model to use Google Search tool and return strict JSON
        user_prompt = (
            f"Search the web (use Google Search tool) for the official metadata of the paper titled: '{title}'. "
            "Locate the paper's official page (publisher, conference, arXiv, DOI landing page, or publisher website) and extract at least three real references (works cited by that paper or referenced works closely related). "
            "For each reference extract: title, authors (comma-separated string), and year (integer). "
            "Return ONLY a JSON array of objects with keys: title, authors, year. No markdown, no commentary."
        )

        # Configure generation call
        generate_kwargs = {
            "model": DEFAULT_MODEL,
            # Tools requested so Gemini performs live search; this is the required setting
            "tools": [{"google_search": {}}],
            # Provide system instruction and user prompt
            "instructions": [
                {"role": "system", "content": SYSTEM_INSTRUCTION},
                {"role": "user", "content": user_prompt}
            ],
            # Safety and size limits
            "max_output_tokens": 1024,
            "temperature": 0.0
        }

        # Call the Gemini client. The exact API surface may vary by package version; try common entrypoints.
        try:
            # Preferred: a unified generate/chat API
            response = genai.generate(**generate_kwargs)
            # Extract text output depending on response shape
            text = None
            # Common shapes: response.output[0].content[0].text or response.output_text
            if hasattr(response, 'output'):
                # try to extract textual content
                try:
                    outputs = response.output
                    if isinstance(outputs, (list, tuple)) and len(outputs) > 0:
                        # support nested content
                        first = outputs[0]
                        if isinstance(first, dict) and 'content' in first:
                            parts = first['content']
                            if isinstance(parts, (list, tuple)) and len(parts) > 0:
                                # find the first text piece
                                for p in parts:
                                    if isinstance(p, dict) and p.get('type') in ('output_text', 'text'):
                                        text = p.get('text') or p.get('content')
                                        break
                        elif isinstance(first, dict) and 'text' in first:
                            text = first['text']
                except Exception:
                    text = None
            if not text and hasattr(response, 'output_text'):
                text = response.output_text
            if not text and isinstance(response, dict):
                # fallback to serialized choices
                text = json.dumps(response)

        except TypeError:
            # Fallback API call shape used by some versions: genai.chat.create or genai.models.generate
            try:
                if hasattr(genai, 'chat') and hasattr(genai.chat, 'create'):
                    response = genai.chat.create(model=DEFAULT_MODEL, instructions=[{"role": "system", "content": SYSTEM_INSTRUCTION}, {"role": "user", "content": user_prompt}], tools=[{"google_search": {}}], temperature=0.0, max_output_tokens=1024)
                    text = getattr(response, 'output_text', None) or json.dumps(response)
                elif hasattr(genai, 'models') and hasattr(genai.models, 'generate'):
                    response = genai.models.generate(model=DEFAULT_MODEL, messages=[{"role": "system", "content": SYSTEM_INSTRUCTION}, {"role": "user", "content": user_prompt}], tools=[{"google_search": {}}], temperature=0.0)
                    text = response.output_text if hasattr(response, 'output_text') else json.dumps(response)
                else:
                    raise
            except Exception as e:
                logger.exception("Gemini client call failed: %s", e)
                raise RuntimeError("Failed to call Gemini API: %s" % e)

        # Ensure we have a textual result
        if not text:
            raise RuntimeError("No textual output from Gemini response")

        # The model is instructed to output pure JSON. Parse it.
        try:
            # Some models may return surrounding whitespace/newlines - strip
            candidate = text.strip()
            # If the model returns additional non-json text, attempt to find first '[' and last ']' to extract JSON array
            if not (candidate.startswith('[') and candidate.endswith(']')):
                first = candidate.find('[')
                last = candidate.rfind(']')
                if first != -1 and last != -1 and last > first:
                    candidate = candidate[first:last+1]
            results = json.loads(candidate)
            # Validate format: list of objects with required keys
            if not isinstance(results, list):
                raise ValueError('Parsed JSON is not a list')
            for item in results:
                if not all(k in item for k in ('title', 'authors', 'year')):
                    raise ValueError('Each item must contain title, authors, and year')
        except Exception as e:
            logger.exception("Failed to parse JSON from model output: %s", e)
            return jsonify({"error": "Failed to parse Gemini output as JSON", "details": str(e), "raw_output": text}), 500

        # Success
        return jsonify(results), 200

    except Exception as e:
        logger.exception("Unhandled error in /search: %s", e)
        return jsonify({"error": "Internal server error", "details": str(e)}), 500


if __name__ == '__main__':
    # Run a development server. In production, use a WSGI server.
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)))
