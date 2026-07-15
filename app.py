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

# Use GEMINI_API_KEY environment variable per requirements
GEMINI_API_KEY = os.environ.get('GEMINI_API_KEY')
if GEMINI_API_KEY:
    try:
        genai.configure(api_key=GEMINI_API_KEY)
    except Exception:
        logging.exception('Failed to configure Gemini client')
else:
    logging.warning('GEMINI_API_KEY not set; Gemini calls will be skipped or use fallback heuristic')

SEMANTIC_SCHOLAR_BASE = 'https://api.semanticscholar.org/graph/v1'


def extract_text_from_pdf_bytes(pdf_bytes: bytes, last_n_pages: int = 5) -> str:
    """Extract text from the last_n_pages of the PDF; if empty, fall back to whole document."""
    reader = PdfReader(io.BytesIO(pdf_bytes))
    num_pages = len(reader.pages)
    start = max(0, num_pages - last_n_pages)
    text_parts: List[str] = []
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
    # fallback to entire document
    text_parts = []
    for i in range(num_pages):
        try:
            page = reader.pages[i]
            txt = page.extract_text() or ""
            text_parts.append(txt)
        except Exception:
            continue
    return "\n".join(text_parts)


def call_gemini_extract_references(text: str, max_items: int = 5) -> List[Dict[str, Any]]:
    """Call Gemini to extract up to max_items references as JSON array of {title, authors, year}."""
    system_instr = (
        "You are a precise extractor. Given a block of text that contains the References section of an academic paper,"
        " extract up to " + str(max_items) + " cited works. For each cited work return an object with exactly these keys:"
        " title (string), authors (string, comma-separated), year (integer or null)."
        " Output MUST be a pure JSON array (no markdown, no backticks, no extra commentary)."
    )
    user_msg = "\n\nText:\n" + text

    if not GEMINI_API_KEY:
        logging.warning('GEMINI not configured; falling back to heuristic extraction')
        # simple heuristic: collect lines that look like citations (contain a 4-digit year)
        lines = [l.strip() for l in text.splitlines() if l.strip()]
        candidates = []
        for l in lines:
            # naive detection of year
            for y in range(1900, 2031):
                if str(y) in l:
                    candidates.append({"title": l[:240], "authors": None, "year": y})
                    break
            if len(candidates) >= max_items:
                break
        return candidates

    try:
        # messages: system then user
        messages = [
            {"role": "system", "content": system_instr},
            {"role": "user", "content": user_msg}
        ]
        resp = genai.chat.create(model="gemini-1.5-flash", messages=messages, max_output_tokens=800)
        # Extract textual content from response robustly
        content = ''
        try:
            # common SDK shapes
            if isinstance(resp, dict):
                if 'candidates' in resp and resp['candidates']:
                    candidate = resp['candidates'][0]
                    if isinstance(candidate, dict):
                        content = candidate.get('content') or candidate.get('message') or ''
                elif 'output' in resp:
                    out = resp['output']
                    if isinstance(out, list):
                        content = ' '.join([str(o) for o in out])
                    else:
                        content = str(out)
            else:
                # object-like
                try:
                    content = resp.candidates[0].content
                except Exception:
                    content = str(resp)
        except Exception:
            content = str(resp)

        # find JSON array in content
        start = content.find('[')
        end = content.rfind(']')
        json_blob = content[start:end+1] if start != -1 and end != -1 and end > start else content
        parsed = json.loads(json_blob)
        results: List[Dict[str, Any]] = []
        for item in parsed[:max_items]:
            if not isinstance(item, dict):
                continue
            title = item.get('title')
            authors = item.get('authors')
            year = item.get('year')
            try:
                if isinstance(year, str) and year.isdigit():
                    year = int(year)
                elif isinstance(year, (int, float)):
                    year = int(year)
                else:
                    year = None
            except Exception:
                year = None
            results.append({"title": title, "authors": authors, "year": year})
        return results
    except Exception:
        logging.exception('Gemini extraction failed; returning empty list')
        return []


def search_semanticscholar_for_title(title: str) -> Dict[str, Any]:
    """Search Semantic Scholar and return one best match with open pdf if available."""
    if not title:
        return {"title": None, "authors": None, "year": None, "pdf_url": None}
    q = urllib.parse.quote_plus(title)
    url = f"{SEMANTIC_SCHOLAR_BASE}/paper/search?query={q}&fields=title,authors,year,openAccessPdf&limit=5"
    try:
        r = requests.get(url, headers={"User-Agent": "jernalsearch/1.0"}, timeout=12)
        if r.status_code != 200:
            logging.warning('Semantic Scholar returned %s for query %s', r.status_code, title)
            return {"title": title, "authors": None, "year": None, "pdf_url": None}
        data = r.json()
        items = data.get('data') or []
        for it in items:
            pdf_url = None
            open_pdf = it.get('openAccessPdf')
            if isinstance(open_pdf, dict):
                pdf_url = open_pdf.get('url')
            elif isinstance(open_pdf, str):
                pdf_url = open_pdf
            # fallback: check other fields
            if not pdf_url:
                for f in ('url', 'externalUrls', 'external_urls'):
                    val = it.get(f)
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
    except Exception:
        logging.exception('Error querying Semantic Scholar for title: %s', title)
    return {"title": title, "authors": None, "year": None, "pdf_url": None}


@app.route('/')
def index():
    return render_template('index.html')


@app.route('/api/upload-pdf', methods=['POST'])
def upload_pdf():
    """Accepts a multipart/form-data file field named 'file', extracts references, searches for PDFs, returns list."""
    uploaded = request.files.get('file')
    if not uploaded:
        return jsonify({"error": "no file uploaded"}), 400
    try:
        pdf_bytes = uploaded.read()
        text = extract_text_from_pdf_bytes(pdf_bytes, last_n_pages=5)
        logging.info('Extracted text length=%d', len(text) if text else 0)

        refs = call_gemini_extract_references(text, max_items=5)
        results: List[Dict[str, Any]] = []
        for r in refs:
            title = r.get('title') if r else None
            authors = r.get('authors') if r else None
            year = r.get('year') if r else None
            if not title:
                continue
            ss = search_semanticscholar_for_title(title)
            out_title = ss.get('title') or title
            out_authors = ss.get('authors') or authors
            out_year = ss.get('year') or year
            pdf_url = ss.get('pdf_url') if ss.get('pdf_url') else None
            results.append({"title": out_title, "authors": out_authors, "year": out_year, "pdf_url": pdf_url})

        # dedupe by normalized title
        seen = set()
        dedup = []
        for it in results:
            key = (it.get('title') or '').strip().lower()
            if key and key not in seen:
                seen.add(key)
                dedup.append(it)
        return jsonify(dedup)
    except Exception:
        logging.exception('Failed to process uploaded PDF')
        return jsonify({"error": "internal server error"}), 500


if __name__ == '__main__':
    app.run(host='0.0.0.0', port=int(os.environ.get('PORT', 5000)), debug=True)

