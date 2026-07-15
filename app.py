import os
import io
import json
import logging
import urllib.parse
from typing import List, Dict, Any
from flask import Flask, request, jsonify, render_template
from flask_cors import CORS, cross_origin
import requests
from pypdf import PdfReader

# Try to import pdfplumber as fallback
try:
    import pdfplumber
    HAS_PDFPLUMBER = True
except ImportError:
    HAS_PDFPLUMBER = False
    pdfplumber = None

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
    """Extract text from the last_n_pages of the PDF using pypdf; fallback to pdfplumber if needed."""
    text = ""
    
    # Try pypdf first
    try:
        reader = PdfReader(io.BytesIO(pdf_bytes))
        num_pages = len(reader.pages)
        start = max(0, num_pages - last_n_pages)
        text_parts: List[str] = []
        
        for i in range(start, num_pages):
            try:
                page = reader.pages[i]
                txt = page.extract_text() or ""
                text_parts.append(txt)
            except Exception as e:
                logging.warning(f'Failed to extract text from pypdf page {i}: {e}')
                continue
        
        text = "\n".join(text_parts).strip()
        
        # If last_n_pages returned empty, try full document
        if not text:
            text_parts = []
            for i in range(num_pages):
                try:
                    page = reader.pages[i]
                    txt = page.extract_text() or ""
                    text_parts.append(txt)
                except Exception as e:
                    logging.warning(f'Failed to extract text from pypdf page {i}: {e}')
                    continue
            text = "\n".join(text_parts)
    
    except Exception as e:
        logging.warning(f'pypdf extraction failed: {e}. Trying pdfplumber...')
    
    # Fallback to pdfplumber if pypdf didn't work or returned empty
    if not text and HAS_PDFPLUMBER:
        try:
            with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
                num_pages = len(pdf.pages)
                start = max(0, num_pages - last_n_pages)
                text_parts = []
                
                for i in range(start, num_pages):
                    try:
                        page = pdf.pages[i]
                        txt = page.extract_text() or ""
                        text_parts.append(txt)
                    except Exception as e:
                        logging.warning(f'Failed to extract text from pdfplumber page {i}: {e}')
                        continue
                
                text = "\n".join(text_parts).strip()
                
                # If last_n_pages returned empty, try full document
                if not text:
                    text_parts = []
                    for i in range(num_pages):
                        try:
                            page = pdf.pages[i]
                            txt = page.extract_text() or ""
                            text_parts.append(txt)
                        except Exception as e:
                            logging.warning(f'Failed to extract text from pdfplumber page {i}: {e}')
                            continue
                    text = "\n".join(text_parts)
        except Exception as e:
            logging.error(f'pdfplumber extraction also failed: {e}')
    
    if not text:
        raise ValueError("Unable to extract text from PDF using any available method")
    
    return text


def call_gemini_extract_references(text: str, max_items: int = 5) -> List[Dict[str, Any]]:
    """Call Gemini to extract up to max_items references as JSON array of {title, authors, year}.
    This function sanitizes Gemini output by removing markdown code fences and extracting the first JSON array found.
    """
    import re
    system_instr = (
        "You are a precise extractor. Given a block of text that contains the References section of an academic paper,"
        " extract up to " + str(max_items) + " cited works. For each cited work return an object with exactly these keys:"
        " title (string), authors (string, comma-separated), year (integer or null)."
        " Output MUST be a pure JSON array (no markdown, no backticks, no extra commentary)."
    )
    user_msg = "\n\nText:\n" + text

    if not GEMINI_API_KEY:
        logging.warning('GEMINI not configured; falling back to heuristic extraction')
        lines = [l.strip() for l in text.splitlines() if l.strip()]
        candidates = []
        for l in lines:
            for y in range(1900, 2031):
                if str(y) in l:
                    candidates.append({"title": l[:240], "authors": None, "year": y})
                    break
            if len(candidates) >= max_items:
                break
        return candidates

    try:
        messages = [
            {"role": "system", "content": system_instr},
            {"role": "user", "content": user_msg}
        ]
        resp = genai.chat.create(model="gemini-1.5-flash", messages=messages, max_output_tokens=800)

        # Extract textual content safely
        content = ''
        try:
            if isinstance(resp, dict):
                if 'candidates' in resp and resp['candidates']:
                    candidate = resp['candidates'][0]
                    if isinstance(candidate, dict):
                        content = candidate.get('content') or candidate.get('message') or ''
                elif 'output' in resp:
                    out = resp['output']
                    content = ' '.join([str(o) for o in out]) if isinstance(out, list) else str(out)
            else:
                content = getattr(resp, 'output_text', None) or str(resp)
        except Exception:
            content = str(resp)

        # Sanitize common markdown wrappers like ```json ... ``` or ``` ... ```
        content = re.sub(r"```json\s*", "", content, flags=re.IGNORECASE)
        content = re.sub(r"```\s*", "", content)

        # Attempt to extract the first JSON array from the content
        m = re.search(r"(\[\s*\{.*?\}\s*\])", content, flags=re.DOTALL)
        json_blob = None
        if m:
            json_blob = m.group(1)
        else:
            # fallback: find first '[' and last ']' and take substring
            start = content.find('[')
            end = content.rfind(']')
            if start != -1 and end != -1 and end > start:
                json_blob = content[start:end+1]
            else:
                json_blob = content

        # Clean up any remaining backticks
        json_blob = json_blob.replace('`', '')

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
    except Exception as e:
        logging.exception('Gemini extraction failed; returning empty list: %s', e)
        print(f"[ERROR] Gemini extraction/parsing failed: {str(e)}")
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


@app.route('/api/upload-pdf', methods=['GET', 'POST', 'OPTIONS'])
@cross_origin(methods=['GET', 'POST', 'OPTIONS'], send_wildcard=True, max_age=3600)
def upload_pdf():
    """Accepts a multipart/form-data file field named 'file', extracts references.
    Enhanced error reporting: returns file name, detailed errors, and debug info.
    """
    # Handle OPTIONS preflight
    if request.method == 'OPTIONS':
        print(f"[DEBUG] OPTIONS preflight handled by @cross_origin decorator")
        return jsonify({"status": "ok"}), 200
    
    # Handle GET request (info)
    if request.method == 'GET':
        return jsonify({"message": "PDF upload endpoint. Send POST with multipart/form-data and 'file' field."}), 200
    
    try:
        print(f"[DEBUG] ===== PDF UPLOAD REQUEST START =====")
        print(f"[DEBUG] Method: {request.method}")
        print(f"[DEBUG] Path: {request.path}")
        print(f"[DEBUG] Content-Type: {request.content_type}")
        print(f"[DEBUG] Content-Length: {request.content_length}")
        print(f"[DEBUG] Form data keys: {list(request.form.keys())}")
        print(f"[DEBUG] File keys: {list(request.files.keys())}")

        uploaded = request.files.get('file')
        print(f"[DEBUG] request.files keys: {list(request.files.keys())}")
        
        if not uploaded:
            print("[ERROR] no file part in request.files")
            return jsonify({
                "success": False,
                "filename": None,
                "error": "no file uploaded. Ensure the request is multipart/form-data with field name 'file'.",
                "debug_info": f"Available fields: {list(request.files.keys())}"
            }), 400

        # Capture filename for error reporting
        filename = uploaded.filename or "unknown"
        print(f"[DEBUG] Processing file: {filename}")

        # Read bytes
        try:
            pdf_bytes = uploaded.read()
            print(f"[DEBUG] Read pdf bytes length: {len(pdf_bytes) if pdf_bytes else 0}")
            
            if not pdf_bytes:
                return jsonify({
                    "success": False,
                    "filename": filename,
                    "error": "File is empty (0 bytes)",
                    "debug_info": "The uploaded file contains no data"
                }), 400
                
        except Exception as e:
            error_msg = str(e)
            print(f"[ERROR] 파일 읽기 실패: {error_msg}")
            logging.exception('파일 읽기 실패')
            return jsonify({
                "success": False,
                "filename": filename,
                "error": f"File read failed: {error_msg}",
                "debug_info": f"Exception type: {type(e).__name__}"
            }), 500

        # Extract text
        try:
            text = extract_text_from_pdf_bytes(pdf_bytes, last_n_pages=5)
            logging.info('Extracted text length=%d from file: %s', len(text) if text else 0, filename)
            print(f"[DEBUG] Successfully extracted text from {filename}: {len(text)} characters")
            
        except Exception as e:
            error_msg = str(e)
            print(f"[ERROR] PDF 파싱 중 에러 발생 ({filename}): {error_msg}")
            logging.exception('PDF 파싱 실패')
            return jsonify({
                "success": False,
                "filename": filename,
                "error": f"PDF parsing failed: {error_msg}",
                "debug_info": f"Exception: {type(e).__name__}. Ensure the file is a valid PDF."
            }), 500

        # Call Gemini to extract references
        try:
            refs = call_gemini_extract_references(text, max_items=5)
            print(f"[DEBUG] Extracted {len(refs)} references from {filename}")
            
        except Exception as e:
            error_msg = str(e)
            print(f"[ERROR] Gemini 처리 중 에러 발생 ({filename}): {error_msg}")
            logging.exception('Gemini 호출 실패')
            return jsonify({
                "success": False,
                "filename": filename,
                "error": f"Gemini processing failed: {error_msg}",
                "debug_info": f"Exception: {type(e).__name__}. Check GEMINI_API_KEY environment variable."
            }), 500

        # Validate refs
        if not isinstance(refs, list):
            print(f"[ERROR] Gemini 반환 형식 오류 ({filename}): {type(refs)}")
            logging.error('Gemini 반환 형식 오류')
            return jsonify({
                "success": False,
                "filename": filename,
                "error": "Invalid response format from Gemini",
                "debug_info": f"Expected list, got {type(refs).__name__}"
            }), 500

        # Clean and prepare references
        cleaned = []
        seen = set()
        for r in refs:
            if not isinstance(r, dict):
                continue
            title = (r.get('title') or '').strip()
            authors = (r.get('authors') or '').strip() if r.get('authors') else None
            year = r.get('year') if r.get('year') else None
            if isinstance(year, str) and year.isdigit():
                try:
                    year = int(year)
                except:
                    year = None
            key = title.lower()
            if not title or key in seen:
                continue
            seen.add(key)
            cleaned.append({"title": title, "authors": authors, "year": year})

        print(f"[DEBUG] Successfully processed {filename}: {len(cleaned)} cleaned references")
        
        # Return extracted full text plus the extracted reference metadata
        return jsonify({
            "success": True,
            "filename": filename,
            "extracted_text": text,
            "references": cleaned,
            "reference_count": len(cleaned)
        }), 200
        
    except Exception as e:
        error_msg = str(e)
        filename = "unknown"
        try:
            uploaded = request.files.get('file')
            if uploaded:
                filename = uploaded.filename or "unknown"
        except:
            pass
        
        print(f"[ERROR] 업로드 처리 중 예외 발생 ({filename}): {error_msg}")
        logging.exception('업로드 처리 중 예외')
        return jsonify({
            "success": False,
            "filename": filename,
            "error": f"Server error: {error_msg}",
            "debug_info": f"Exception type: {type(e).__name__}"
        }), 500


@app.errorhandler(405)
def method_not_allowed(e):
    return jsonify({"error": "Method Not Allowed. This endpoint only accepts POST requests."}), 405

@app.errorhandler(404)
def not_found(e):
    return jsonify({"error": "Not Found (404). Please check the URL."}), 404

if __name__ == '__main__':
    port = int(os.environ.get('PORT', 5002))
    print(f"[INFO] Starting server on port {port}")
    print(f"[INFO] pdfplumber available: {HAS_PDFPLUMBER}")
    app.run(host='0.0.0.0', port=port, debug=True)

