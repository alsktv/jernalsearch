import os
import io
import json
import logging
import urllib.parse
from typing import List, Dict, Any
from flask import Flask, request, jsonify, render_template
from flask_cors import CORS
import requests
from pypdf import PdfReader

# Google Generative AI (Gemini)
import google.generativeai as genai

logging.basicConfig(level=logging.INFO)
app = Flask(__name__, template_folder='templates')
CORS(app)

# Configure Gemini API key from environment
GENAI_API_KEY = os.environ.get('GOOGLE_API_KEY') or os.environ.get('GENAI_API_KEY')
if GENAI_API_KEY:
    genai.configure(api_key=GENAI_API_KEY)
else:
    logging.warning('Google Generative AI API key not found in environment (GOOGLE_API_KEY or GENAI_API_KEY)')

SEMANTIC_SCHOLAR_BASE = 'https://api.semanticscholar.org/graph/v1'


def extract_text_from_pdf_bytes(pdf_bytes: bytes, last_n_pages: int = 8) -> str:
    reader = PdfReader(io.BytesIO(pdf_bytes))
    num_pages = len(reader.pages)
    start = max(0, num_pages - last_n_pages)
    text_parts: List[str] = []
    # Try last_n_pages first
    for i in range(start, num_pages):
        try:
            page = reader.pages[i]
            txt = page.extract_text() or ""
            text_parts.append(txt)
        except Exception:
            continue
    combined = "\n".join(text_parts).strip()
    if combined:
        return combined
    # Fallback: read whole document
    text_parts = []
    for i in range(num_pages):
        try:
            page = reader.pages[i]
            txt = page.extract_text() or ""
            text_parts.append(txt)
        except Exception:
            continue
    return "\n".join(text_parts)


def call_gemini_extract_references(text: str) -> List[Dict[str, Any]]:
    # Prompt instructing Gemini to output strict JSON
    prompt = (
        "Extract the References section from the provided text. Return a JSON array only (no extra text)."
        " Each item should be an object with keys: title, authors (single string), year (number if available or null)."
        " If a reference lacks a year or authors, use null for that field. Parse titles accurately and avoid adding items that are not bibliographic references."
        "\n\nText:\n" + text
    )

    if not GENAI_API_KEY:
        # As a fallback when Gemini is not configured, attempt a simple heuristic: lines with years
        logging.warning('Gemini not configured; using simple fallback heuristic to extract candidate lines')
        lines = [l.strip() for l in text.splitlines() if l.strip()]
        candidates = []
        for l in lines:
            # naive: line containing a four-digit year
            if any(str(y) in l for y in range(1900, 2031)):
                candidates.append({"title": l[:200], "authors": None, "year": None})
        return candidates[:50]

    try:
        response = genai.chat.create(model="gemini-1.5-flash", messages=[{"role": "user", "content": prompt}], max_output_tokens=1024)
        # The exact response shape may vary; attempt to find JSON
        content = ''
        if isinstance(response, dict):
            # new API shapes might put text in response['candidates'][0]['content'] or response['output'][0]
            if 'candidates' in response and response['candidates']:
                content = response['candidates'][0].get('content', '')
            elif 'output' in response:
                # try to join outputs
                if isinstance(response['output'], list):
                    content = ' '.join([str(o) for o in response['output']])
                else:
                    content = str(response['output'])
        else:
            # some SDKs return object-like responses
            try:
                content = response.candidates[0].content
            except Exception:
                content = str(response)

        # Attempt to extract JSON substring
        start_idx = content.find('[')
        end_idx = content.rfind(']')
        if start_idx != -1 and end_idx != -1:
            json_str = content[start_idx:end_idx+1]
        else:
            json_str = content

        parsed = json.loads(json_str)
        # Normalize items
        results = []
        for item in parsed:
            title = item.get('title') if isinstance(item, dict) else None
            authors = item.get('authors') if isinstance(item, dict) else None
            year = item.get('year') if isinstance(item, dict) else None
            try:
                if isinstance(year, str) and year.isdigit():
                    year = int(year)
            except Exception:
                year = None
            results.append({
                'title': title,
                'authors': authors,
                'year': year
            })
        return results
    except Exception as e:
        logging.exception('Error calling Gemini: %s', e)
        return []


def search_semanticscholar_for_title(title: str) -> Dict[str, Any]:
    if not title:
        return {"title": None, "authors": None, "year": None, "pdf_url": None}
    q = urllib.parse.quote_plus(title)
    url = f"{SEMANTIC_SCHOLAR_BASE}/paper/search?query={q}&fields=title,authors,year,openAccessPdf&limit=5"
    try:
        resp = requests.get(url, headers={"User-Agent": "jernalsearch/1.0"}, timeout=15)
        if resp.status_code != 200:
            logging.warning('Semantic Scholar non-200: %s for title %s', resp.status_code, title)
            return {"title": title, "authors": None, "year": None, "pdf_url": None}
        data = resp.json()
        # data is expected to have 'data' list
        items = data.get('data') or data.get('results') or []
        for it in items:
            # pick first with an openAccessPdf
            open_pdf = it.get('openAccessPdf')
            pdf_url = None
            if open_pdf:
                # sometimes openAccessPdf is an object with 'url'
                if isinstance(open_pdf, dict):
                    pdf_url = open_pdf.get('url')
                elif isinstance(open_pdf, str):
                    pdf_url = open_pdf
            # Also try to find direct pdf link within other fields
            if not pdf_url:
                # try searching for '.pdf' in external_urls or url fields
                for candidate_field in ['url', 'externalUrls', 'external_urls']:
                    val = it.get(candidate_field)
                    if isinstance(val, str) and val.lower().endswith('.pdf'):
                        pdf_url = val
                        break
                    if isinstance(val, list):
                        for v in val:
                            if isinstance(v, str) and '.pdf' in v.lower():
                                pdf_url = v
                                break
                        if pdf_url:
                            break

            authors_list = it.get('authors') or []
            authors = ', '.join([a.get('name') for a in authors_list if a.get('name')]) if authors_list else None
            year = it.get('year') or None
            return {"title": it.get('title') or title, "authors": authors, "year": year, "pdf_url": pdf_url}
        # nothing matched
        return {"title": title, "authors": None, "year": None, "pdf_url": None}
    except Exception as e:
        logging.exception('Error searching Semantic Scholar for title: %s', title)
        return {"title": title, "authors": None, "year": None, "pdf_url": None}


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/api/upload-pdf', methods=['POST'])
def upload_pdf():
    file = request.files.get('file')
    if not file:
        return jsonify({"error": "no file uploaded"}), 400
    try:
        pdf_bytes = file.read()
        # Extract text from last few pages where References usually reside
        text = extract_text_from_pdf_bytes(pdf_bytes, last_n_pages=10)
        logging.info('Extracted text length: %d', len(text) if text else 0)

        # Call Gemini to extract references
        references = call_gemini_extract_references(text)

        # For each reference, search Semantic Scholar for open access pdf
        results = []
        for ref in references:
            title = ref.get('title') if ref else None
            authors = ref.get('authors') if ref else None
            year = ref.get('year') if ref else None
            if not title:
                continue
            ss = search_semanticscholar_for_title(title)
            # prefer richer metadata from Semantic Scholar if available
            out_title = ss.get('title') or title
            out_authors = ss.get('authors') or authors
            out_year = ss.get('year') or year
            out_pdf = ss.get('pdf_url') if ss.get('pdf_url') else None
            results.append({
                'title': out_title,
                'authors': out_authors,
                'year': out_year,
                'pdf_url': out_pdf
            })

        # Deduplicate by title
        seen = set()
        deduped = []
        for r in results:
            key = (r.get('title') or '').strip()
            if key and key.lower() not in seen:
                seen.add(key.lower())
                deduped.append(r)

        return jsonify(deduped)
    except Exception as e:
        logging.exception('Error processing uploaded PDF: %s', e)
        return jsonify({"error": "internal server error"}), 500


if __name__ == '__main__':
    # Use port 5000 by default
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)), debug=True)

