"""
Multilingual Plagiarism & AI Writing Detector Pro — Internet Server Edition
Author: Dilshod Xo'jayev — Uzbekistan State World Languages University

This backend performs automatic internet source checking without showing search
settings in the browser interface. It combines open web-result pages, academic
metadata services, and university-domain queries. It returns real URLs only and
never invents sources.
"""
from __future__ import annotations

import datetime as dt
import hashlib
import html
import os
import re
import secrets
import time
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Optional
from urllib.parse import parse_qs, quote_plus, unquote, urlparse

import httpx
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Header, HTTPException, UploadFile, File
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse
from pydantic import BaseModel, Field

load_dotenv()

# --------------------------------------------------------------------------- #
# Config
# --------------------------------------------------------------------------- #
# These environment variables are optional and hidden from the user interface.
SEARCH_PROVIDER = os.getenv("SEARCH_PROVIDER", "internet_server_all").lower().strip()
SEARCH_API_KEY = os.getenv("SEARCH_API_KEY", "").strip()
GOOGLE_CSE_ID = os.getenv("GOOGLE_CSE_ID", os.getenv("SEARCH_CX", "")).strip()
BING_ENDPOINT = os.getenv("BING_ENDPOINT", "https://api.bing.microsoft.com/v7.0/search").strip()
SERPAPI_API_KEY = os.getenv("SERPAPI_API_KEY", "").strip()
JWT_SECRET = os.getenv("JWT_SECRET", "dev-only-change-me")
ALLOW_ORIGINS = [o.strip() for o in os.getenv("ALLOW_ORIGINS", "*").split(",") if o.strip()]

BASE_DIR = Path(__file__).resolve().parent
PROJECT_DIR = BASE_DIR.parent if BASE_DIR.name == "backend" else BASE_DIR
INDEX_HTML = PROJECT_DIR / "index.html"

app = FastAPI(title="Plagiarism Detector Pro Internet Server", version="3.0.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOW_ORIGINS or ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --------------------------------------------------------------------------- #
# Models
# --------------------------------------------------------------------------- #
class Credentials(BaseModel):
    email: str
    password: str
    remember: bool = False

class SearchSourcesRequest(BaseModel):
    text: str = Field(..., min_length=1)
    max_phrases: int = Field(default=6, ge=1, le=10)
    provider: Optional[str] = None

class AnalyzeRequest(BaseModel):
    text: str
    language: Optional[str] = None
    online: bool = False

class Issue(BaseModel):
    type: str
    start: int
    end: int
    explanation: str
    suggestion: Optional[str] = None

class AnalyzeResponse(BaseModel):
    language: str
    word_count: int
    char_count: int
    scores: dict
    grade: str
    ai_probability: float
    human_probability: float
    plagiarism: float
    originality: float
    issues: list[Issue]
    sources: list[dict]
    notice: str

# --------------------------------------------------------------------------- #
# Small auth demo
# --------------------------------------------------------------------------- #
_USERS: dict[str, dict] = {}

def _hash_pw(pw: str, salt: str) -> str:
    return hashlib.pbkdf2_hmac("sha256", pw.encode(), salt.encode(), 200_000).hex()

def issue_token(email: str, role: str) -> str:
    raw = f"{email}:{role}:{secrets.token_hex(16)}"
    return hashlib.sha256((raw + JWT_SECRET).encode()).hexdigest() + "." + email

def current_user_optional(authorization: str = Header(default="")) -> dict:
    if not authorization.startswith("Bearer "):
        return {"email": "guest", "role": "guest"}
    token = authorization[7:]
    if "." not in token:
        return {"email": "guest", "role": "guest"}
    email = token.rsplit(".", 1)[1]
    user = _USERS.get(email)
    if not user:
        return {"email": "guest", "role": "guest"}
    return {"email": email, "role": user["role"]}

@app.post("/api/register")
def register(c: Credentials):
    if c.email in _USERS:
        raise HTTPException(409, "Email already registered")
    salt = secrets.token_hex(8)
    role = "admin" if c.email.startswith("admin@") else "user"
    _USERS[c.email] = {"hash": _hash_pw(c.password, salt), "salt": salt, "role": role}
    return {"token": issue_token(c.email, role), "role": role}

@app.post("/api/login")
def login(c: Credentials):
    user = _USERS.get(c.email)
    if not user or _hash_pw(c.password, user["salt"]) != user["hash"]:
        raise HTTPException(401, "Invalid email or password")
    return {"token": issue_token(c.email, user["role"]), "role": user["role"]}

# --------------------------------------------------------------------------- #
# Front-end serving
# --------------------------------------------------------------------------- #
@app.get("/", response_class=HTMLResponse)
def app_home():
    if INDEX_HTML.exists():
        return FileResponse(INDEX_HTML)
    return HTMLResponse("<h1>index.html not found</h1>", status_code=404)

@app.get("/index.html", response_class=HTMLResponse)
def app_index():
    return app_home()

# --------------------------------------------------------------------------- #
# Text utilities
# --------------------------------------------------------------------------- #
WORD_RE = re.compile(r"[\wʻʼ’'-]+", re.UNICODE)
CJK_RE = re.compile(r"[\u4e00-\u9fff]")

def words(text: str) -> list[str]:
    return WORD_RE.findall(text or "")

def split_sentences(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?。！？])\s+|\n+", text or "")
    return [p.strip() for p in parts if p.strip()]

def pick_query_phrases(text: str, max_phrases: int = 6) -> list[str]:
    """Pick distinctive verbatim phrases for source search."""
    text = re.sub(r"\s+", " ", text or "").strip()
    if not text:
        return []

    # CJK chunking
    if len(CJK_RE.findall(text)) > max(12, len(text) * 0.15):
        out: list[str] = []
        seen: set[str] = set()
        for sent in sorted(split_sentences(text), key=len, reverse=True):
            sent = re.sub(r"[\"“”'’]", "", sent)
            if len(sent) < 18:
                continue
            for start in (0, max(0, len(sent)//2 - 12)):
                phrase = sent[start:start+32]
                if phrase not in seen:
                    out.append(phrase); seen.add(phrase)
                if len(out) >= max_phrases:
                    return out
        return out[:max_phrases]

    candidates: list[str] = []
    for sent in split_sentences(text):
        toks = words(sent)
        if len(toks) >= 8:
            # Several windows from long sentences improves recall.
            windows = [(0, min(12, len(toks)))]
            if len(toks) >= 16:
                windows.append((max(0, len(toks)//2 - 6), 12))
            if len(toks) >= 24:
                windows.append((len(toks)-12, 12))
            for start, length in windows:
                chunk = toks[start:start+length]
                if len(chunk) >= 8:
                    candidates.append(" ".join(chunk))
    if not candidates:
        toks = words(text)
        for i in range(0, max(1, len(toks)-7), 7):
            chunk = toks[i:i+10]
            if len(chunk) >= 7:
                candidates.append(" ".join(chunk))

    candidates.sort(key=lambda x: (len(x.split()), len(x)), reverse=True)
    out, seen = [], set()
    for cand in candidates:
        cand = re.sub(r"[\"“”]", "", cand).strip()
        key = cand.lower()
        if len(cand) < 25 or key in seen:
            continue
        seen.add(key); out.append(cand)
        if len(out) >= max_phrases:
            break
    return out

def strip_tags(fragment: str) -> str:
    fragment = re.sub(r"<script.*?</script>|<style.*?</style>|<noscript.*?</noscript>", " ", fragment or "", flags=re.I | re.S)
    fragment = re.sub(r"<.*?>", " ", fragment, flags=re.S)
    fragment = html.unescape(fragment)
    return re.sub(r"\s+", " ", fragment).strip()

def normalize_text(s: str) -> str:
    s = html.unescape(s or "").lower()
    s = re.sub(r"[\u2018\u2019\u02bb\u02bc]", "'", s)
    s = re.sub(r"[^\w\s'\-\u4e00-\u9fff]", " ", s, flags=re.UNICODE)
    return re.sub(r"\s+", " ", s).strip()

def overlap_pct(snippet: str, phrase: str) -> float:
    a = set(w.lower() for w in words(phrase))
    if not a:
        return 0.0
    b = set(w.lower() for w in words(snippet or ""))
    if not b:
        return 0.0
    return len(a & b) / len(a)

def clean_url(url: str) -> str:
    if not url:
        return ""
    url = html.unescape(url)
    if url.startswith("//"):
        url = "https:" + url
    parsed = urlparse(url)
    qs = parse_qs(parsed.query)
    for key in ("uddg", "RU", "url", "u"):
        if key in qs and qs[key]:
            val = unquote(qs[key][0])
            if val.startswith(("http://", "https://")):
                return val
            # Bing base64 wrapper: u=a1<base64url>
            if key == "u" and val.startswith("a1"):
                try:
                    import base64
                    raw = val[2:]
                    raw += "=" * ((4 - len(raw) % 4) % 4)
                    decoded = base64.urlsafe_b64decode(raw.encode()).decode("utf-8", "ignore")
                    if decoded.startswith(("http://", "https://")):
                        return decoded
                except Exception:
                    pass
    return url

def domain_of(url: str) -> str:
    try:
        return urlparse(url).netloc.replace("www.", "")
    except Exception:
        return ""

def is_probably_search_noise(url: str) -> bool:
    host = domain_of(url).lower()
    if not host:
        return True
    bad_hosts = {
        "duckduckgo.com", "html.duckduckgo.com", "lite.duckduckgo.com",
        "bing.com", "microsoft.com", "go.microsoft.com", "google.com",
        "accounts.google.com", "support.google.com", "search.yahoo.com",
        "yahoo.com", "brave.com", "search.brave.com", "ecosia.org",
    }
    return host in bad_hosts or host.endswith(".bing.com") or host.endswith(".duckduckgo.com")

def source_strength(best_overlap: float, phrase_count: int, exact_count: int, category: str) -> int:
    base = best_overlap * 62 + phrase_count * 13 + exact_count * 20
    if category == "university":
        base += 4
    if category == "academic":
        base += 2
    return max(20, min(100, round(base)))

def category_for_url(url: str, provider: str = "") -> str:
    host = domain_of(url).lower()
    academic_hosts = ("doi.org", "crossref.org", "openalex.org", "arxiv.org", "semanticscholar.org", "jstor.org", "springer.com", "sciencedirect.com", "tandfonline.com", "researchgate.net", "mdpi.com", "frontiersin.org", "nature.com", "wiley.com", "sagepub.com")
    if any(h in host for h in academic_hosts) or provider.lower().startswith(("openalex", "crossref", "arxiv", "semantic")):
        return "academic"
    university_markers = (".edu", ".ac.", ".edu.", "university", "universitet", "uzswlu.uz", "edu.uz", "ziyonet.uz")
    if any(m in host for m in university_markers):
        return "university"
    return "web"

# --------------------------------------------------------------------------- #
# Search providers
# --------------------------------------------------------------------------- #
def result_item(title: str, url: str, snippet: str, provider: str, category: Optional[str] = None) -> Optional[dict]:
    url = clean_url(url)
    if not url.startswith(("http://", "https://")) or is_probably_search_noise(url):
        return None
    return {
        "title": strip_tags(title) or domain_of(url) or url,
        "url": url,
        "domain": domain_of(url),
        "snippet": strip_tags(snippet)[:520],
        "provider": provider,
        "category": category or category_for_url(url, provider),
    }

def google_cse_search(client: httpx.Client, query: str) -> list[dict]:
    if not (SEARCH_API_KEY and GOOGLE_CSE_ID):
        raise RuntimeError("Google CSE is not configured")
    r = client.get("https://www.googleapis.com/customsearch/v1", params={"key": SEARCH_API_KEY, "cx": GOOGLE_CSE_ID, "num": 7, "q": query})
    data = r.json() if r.content else {}
    if r.status_code >= 400 or data.get("error"):
        msg = data.get("error", {}).get("message") or f"Google CSE HTTP {r.status_code}"
        raise RuntimeError(msg)
    out = []
    for it in data.get("items", []):
        item = result_item(it.get("title", ""), it.get("link", ""), it.get("snippet", ""), "Google web index")
        if item:
            out.append(item)
    return out

def bing_api_search(client: httpx.Client, query: str) -> list[dict]:
    if not SEARCH_API_KEY:
        raise RuntimeError("Bing is not configured")
    r = client.get(BING_ENDPOINT, headers={"Ocp-Apim-Subscription-Key": SEARCH_API_KEY}, params={"q": query, "count": 7, "responseFilter": "Webpages"})
    data = r.json() if r.content else {}
    if r.status_code >= 400:
        raise RuntimeError(data.get("message") or f"Bing HTTP {r.status_code}")
    out = []
    for it in data.get("webPages", {}).get("value", []):
        item = result_item(it.get("name", ""), it.get("url", ""), it.get("snippet", ""), "Bing web index")
        if item:
            out.append(item)
    return out

def serpapi_search(client: httpx.Client, query: str) -> list[dict]:
    key = SERPAPI_API_KEY or SEARCH_API_KEY
    if not key:
        raise RuntimeError("SerpAPI is not configured")
    r = client.get("https://serpapi.com/search.json", params={"engine": "google", "api_key": key, "q": query, "num": 7})
    data = r.json() if r.content else {}
    if r.status_code >= 400 or data.get("error"):
        raise RuntimeError(str(data.get("error") or f"SerpAPI HTTP {r.status_code}"))
    out = []
    for it in data.get("organic_results", []):
        item = result_item(it.get("title", ""), it.get("link", ""), it.get("snippet", ""), "SerpAPI web index")
        if item:
            out.append(item)
    return out

COMMON_HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) InternetSourceChecker/3.0",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "uz,en-US;q=0.9,en;q=0.8,ru;q=0.7",
}


def jina_search(client: httpx.Client, query: str) -> list[dict]:
    """Fast server-side web search via Jina Reader Search.
    It returns real URLs and readable page text, which is more reliable on Render
    than scraping search-result HTML directly. No keys are shown in the interface.
    """
    out: list[dict] = []
    last_error = None
    # Try both official formats: ?q= and path-encoded query.
    urls = [
        ("https://s.jina.ai/", {"q": query}),
        ("https://s.jina.ai/" + quote_plus(query), None),
    ]
    headers = dict(COMMON_HEADERS)
    headers.update({
        "Accept": "text/plain, text/markdown, */*",
        "X-Respond-With": "text",
        "X-No-Cache": "true",
    })
    for endpoint, params in urls:
        try:
            r = client.get(endpoint, params=params, headers=headers, follow_redirects=True, timeout=18.0)
            if r.status_code >= 400:
                last_error = f"Jina Search HTTP {r.status_code}"
                continue
            text = r.text or ""
            # Common Reader format: Title / URL Source / Markdown Content
            pattern = re.compile(
                r"(?:^|\n)Title:\s*(?P<title>.*?)\nURL Source:\s*(?P<url>https?://\S+)(?P<body>.*?)(?=\nTitle:\s|\Z)",
                re.S | re.I,
            )
            for m in pattern.finditer(text):
                body = m.group('body')
                body = re.sub(r"^\s*(Markdown Content|Content|Description):\s*", "", body.strip(), flags=re.I)
                item = result_item(m.group('title'), m.group('url'), body[:1600], "Jina Reader Search")
                if item:
                    out.append(item)
                if len(out) >= 8:
                    return out
            # Fallback: collect any real URLs with nearby text.
            if not out:
                for m in re.finditer(r"https?://[^\s)\]>'\"]+", text):
                    url = m.group(0).rstrip('.,;:')
                    start = max(0, m.start()-350)
                    end = min(len(text), m.end()+900)
                    item = result_item(domain_of(url), url, text[start:end], "Jina Reader Search")
                    if item:
                        out.append(item)
                    if len(out) >= 8:
                        return out
            if out:
                return out[:8]
        except Exception as exc:
            last_error = str(exc)
    if last_error:
        raise RuntimeError(last_error)
    return out[:8]

def duckduckgo_html_search(client: httpx.Client, query: str) -> list[dict]:
    def parse(text: str) -> list[dict]:
        out = []
        blocks = re.split(r'<div[^>]+class="[^"]*(?:result results_links|web-result|result--url-above-snippet)[^"]*"', text, flags=re.I)[1:12]
        for block in blocks:
            a = re.search(r'<a[^>]+class="[^"]*result__a[^"]*"[^>]+href="([^"]+)"[^>]*>(.*?)</a>', block, re.I | re.S)
            if not a:
                a = re.search(r'<a[^>]+href="([^"]+)"[^>]+class="[^"]*result__a[^"]*"[^>]*>(.*?)</a>', block, re.I | re.S)
            if not a:
                continue
            sn = re.search(r'<(?:a|div)[^>]+class="[^"]*result__snippet[^"]*"[^>]*>(.*?)</(?:a|div)>', block, re.I | re.S)
            item = result_item(a.group(2), a.group(1), sn.group(1) if sn else block, "DuckDuckGo web")
            if item:
                out.append(item)
        if not out:
            # Lite result table fallback
            for m in re.finditer(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', text, re.I | re.S):
                nearby = text[m.end():m.end()+700]
                item = result_item(m.group(2), m.group(1), nearby, "DuckDuckGo Lite")
                if item:
                    out.append(item)
                if len(out) >= 8:
                    break
        return out[:8]

    out, last_error = [], None
    for q in (query, query.replace('"', '')):
        for endpoint in ("https://html.duckduckgo.com/html/", "https://duckduckgo.com/html/", "https://lite.duckduckgo.com/lite/"):
            try:
                r = client.get(endpoint, params={"q": q}, headers=COMMON_HEADERS, follow_redirects=True, timeout=12.0)
                if r.status_code >= 400:
                    last_error = f"DuckDuckGo HTTP {r.status_code}"; continue
                out = parse(r.text)
                if out:
                    return out
            except Exception as exc:
                last_error = str(exc)
    if last_error:
        raise RuntimeError(last_error)
    return []

def bing_html_search(client: httpx.Client, query: str) -> list[dict]:
    out, last_error = [], None
    for q in (query, query.replace('"', '')):
        try:
            r = client.get("https://www.bing.com/search", params={"q": q, "count": 10}, headers=COMMON_HEADERS, follow_redirects=True, timeout=12.0)
            if r.status_code >= 400:
                last_error = f"Bing HTTP {r.status_code}"; continue
            blocks = re.findall(r'<li class="b_algo".*?</li>', r.text, flags=re.I | re.S)
            for block in blocks[:10]:
                m = re.search(r'<h2[^>]*>\s*<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', block, flags=re.I | re.S)
                if not m:
                    continue
                pm = re.search(r'<p[^>]*>(.*?)</p>', block, flags=re.I | re.S)
                item = result_item(m.group(2), m.group(1), pm.group(1) if pm else block, "Bing web")
                if item:
                    out.append(item)
            if out:
                return out[:8]
        except Exception as exc:
            last_error = str(exc)
    if last_error:
        raise RuntimeError(last_error)
    return []

def yahoo_html_search(client: httpx.Client, query: str) -> list[dict]:
    out, last_error = [], None
    for q in (query, query.replace('"', '')):
        try:
            r = client.get("https://search.yahoo.com/search", params={"p": q, "n": 10}, headers=COMMON_HEADERS, follow_redirects=True, timeout=12.0)
            if r.status_code >= 400:
                last_error = f"Yahoo HTTP {r.status_code}"; continue
            for m in re.finditer(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', r.text, flags=re.I | re.S):
                item = result_item(m.group(2), m.group(1), r.text[m.end():m.end()+700], "Yahoo web")
                if item:
                    if "yahoo" in item["domain"].lower():
                        continue
                    out.append(item)
                if len(out) >= 8:
                    break
            if out:
                return out[:8]
        except Exception as exc:
            last_error = str(exc)
    if last_error:
        raise RuntimeError(last_error)
    return []

def brave_html_search(client: httpx.Client, query: str) -> list[dict]:
    out, last_error = [], None
    try:
        r = client.get("https://search.brave.com/search", params={"q": query, "source": "web"}, headers=COMMON_HEADERS, follow_redirects=True, timeout=12.0)
        if r.status_code >= 400:
            raise RuntimeError(f"Brave HTTP {r.status_code}")
        # Brave changes markup often; collect external anchors with nearby text.
        for m in re.finditer(r'<a[^>]+href="([^"]+)"[^>]*>(.*?)</a>', r.text, flags=re.I | re.S):
            item = result_item(m.group(2), m.group(1), r.text[m.end():m.end()+700], "Brave web")
            if item:
                out.append(item)
            if len(out) >= 8:
                break
        return out[:8]
    except Exception as exc:
        last_error = str(exc)
    if last_error:
        raise RuntimeError(last_error)
    return []

# --------------------------------------------------------------------------- #
# Academic and university sources
# --------------------------------------------------------------------------- #
def inverted_abstract(inv: dict) -> str:
    if not isinstance(inv, dict):
        return ""
    pos_to_word = []
    for word, positions in inv.items():
        if isinstance(positions, list):
            for p in positions:
                if isinstance(p, int):
                    pos_to_word.append((p, word))
    pos_to_word.sort()
    return " ".join(w for _, w in pos_to_word)

def openalex_search(client: httpx.Client, phrase: str) -> list[dict]:
    out = []
    try:
        r = client.get("https://api.openalex.org/works", params={"search": phrase, "per-page": 6, "mailto": "academic-integrity-checker@example.com"}, timeout=12.0)
        if r.status_code >= 400:
            raise RuntimeError(f"OpenAlex HTTP {r.status_code}")
        data = r.json()
        for it in data.get("results", []):
            title = it.get("display_name") or "Academic source"
            url = (it.get("doi") or "").replace("https://doi.org/", "https://doi.org/")
            if not url:
                loc = it.get("primary_location") or {}
                source = loc.get("source") or {}
                url = loc.get("landing_page_url") or source.get("homepage_url") or it.get("id", "")
            abstract = inverted_abstract(it.get("abstract_inverted_index") or {})
            item = result_item(title, url, abstract or title, "OpenAlex academic", "academic")
            if item:
                out.append(item)
    except Exception as exc:
        raise RuntimeError(str(exc))
    return out[:6]

def crossref_search(client: httpx.Client, phrase: str) -> list[dict]:
    out = []
    try:
        r = client.get("https://api.crossref.org/works", params={"query.bibliographic": phrase, "rows": 6}, headers={"User-Agent": "InternetSourceChecker/3.0 (mailto:academic-integrity-checker@example.com)"}, timeout=12.0)
        if r.status_code >= 400:
            raise RuntimeError(f"Crossref HTTP {r.status_code}")
        data = r.json()
        for it in data.get("message", {}).get("items", []):
            title = " ".join(it.get("title") or []) or "Academic source"
            doi = it.get("DOI", "")
            url = f"https://doi.org/{doi}" if doi else (it.get("URL") or "")
            abstract = strip_tags(it.get("abstract", ""))
            container = " ".join(it.get("container-title") or [])
            item = result_item(title, url, abstract or container or title, "Crossref academic", "academic")
            if item:
                out.append(item)
    except Exception as exc:
        raise RuntimeError(str(exc))
    return out[:6]

def arxiv_search(client: httpx.Client, phrase: str) -> list[dict]:
    out = []
    try:
        query = f'all:"{phrase}"'
        r = client.get("https://export.arxiv.org/api/query", params={"search_query": query, "start": 0, "max_results": 5}, timeout=12.0)
        if r.status_code >= 400:
            raise RuntimeError(f"arXiv HTTP {r.status_code}")
        root = ET.fromstring(r.text)
        ns = {"a": "http://www.w3.org/2005/Atom"}
        for entry in root.findall("a:entry", ns):
            title = (entry.findtext("a:title", default="", namespaces=ns) or "").strip()
            summary = (entry.findtext("a:summary", default="", namespaces=ns) or "").strip()
            url = entry.findtext("a:id", default="", namespaces=ns) or ""
            item = result_item(title, url, summary, "arXiv academic", "academic")
            if item:
                out.append(item)
    except Exception as exc:
        raise RuntimeError(str(exc))
    return out[:5]

def semantic_scholar_search(client: httpx.Client, phrase: str) -> list[dict]:
    out = []
    try:
        r = client.get("https://api.semanticscholar.org/graph/v1/paper/search", params={"query": phrase, "limit": 6, "fields": "title,url,abstract,externalIds"}, timeout=12.0)
        if r.status_code >= 400:
            raise RuntimeError(f"Semantic Scholar HTTP {r.status_code}")
        data = r.json()
        for it in data.get("data", []):
            url = it.get("url") or ""
            ids = it.get("externalIds") or {}
            if not url and ids.get("DOI"):
                url = f"https://doi.org/{ids['DOI']}"
            item = result_item(it.get("title", "Academic source"), url, it.get("abstract", "") or it.get("title", ""), "Semantic Scholar academic", "academic")
            if item:
                out.append(item)
    except Exception as exc:
        raise RuntimeError(str(exc))
    return out[:6]

UNIVERSITY_SCOPES = [
    "site:.edu",
    "site:.ac.uk",
    "site:.edu.au",
    "site:.ac.nz",
    "site:.edu.cn",
    "site:.edu.tr",
    "site:.edu.uz",
    "site:.edu.kz",
    "site:.edu.az",
    "site:.ac.jp",
    "site:.ac.kr",
    "site:edu.uz",
    "site:ziyonet.uz",
    "site:uzswlu.uz",
    "site:.uz universitet",
]

def combined_web_search(client: httpx.Client, query: str, include_extra: bool = True) -> list[dict]:
    combined, seen, errors = [], set(), []
    providers = [jina_search, duckduckgo_html_search, bing_html_search, yahoo_html_search]
    if include_extra:
        providers.append(brave_html_search)
    # Use hidden official providers if the owner configured keys in .env.
    if SEARCH_API_KEY and GOOGLE_CSE_ID:
        providers.insert(0, google_cse_search)
    if SEARCH_API_KEY and "bing" in BING_ENDPOINT.lower():
        providers.insert(0, bing_api_search)
    if SERPAPI_API_KEY:
        providers.insert(0, serpapi_search)
    for fn in providers:
        try:
            items = fn(client, query)
            for it in items:
                url = clean_url(it.get("url", ""))
                if url and url not in seen:
                    it["url"] = url
                    it["category"] = it.get("category") or category_for_url(url, it.get("provider", ""))
                    combined.append(it)
                    seen.add(url)
        except Exception as exc:
            errors.append(str(exc))
    if combined:
        return combined[:24]
    if errors:
        raise RuntimeError("; ".join(errors[:3]))
    return []

def academic_search(client: httpx.Client, phrase: str) -> list[dict]:
    combined, seen = [], set()
    for fn in (openalex_search, crossref_search, semantic_scholar_search, arxiv_search):
        try:
            for it in fn(client, phrase):
                url = clean_url(it.get("url", ""))
                if url and url not in seen:
                    it["category"] = "academic"
                    combined.append(it)
                    seen.add(url)
        except Exception:
            continue
    return combined[:14]

def university_search(client: httpx.Client, phrase: str) -> list[dict]:
    combined, seen = [], set()
    # Search broad academic domains first; keep count limited for speed.
    for scope in UNIVERSITY_SCOPES[:6]:
        query = f'{scope} "{phrase}"'
        try:
            for it in combined_web_search(client, query, include_extra=False):
                url = clean_url(it.get("url", ""))
                if url and url not in seen:
                    it["category"] = "university"
                    it["provider"] = (it.get("provider") or "") + " + university domains"
                    combined.append(it)
                    seen.add(url)
                if len(combined) >= 12:
                    return combined
        except Exception:
            continue
    return combined[:12]

# --------------------------------------------------------------------------- #
# Verification
# --------------------------------------------------------------------------- #
def fetch_page_text(client: httpx.Client, url: str) -> str:
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) InternetSourceChecker/3.0",
        "Accept": "text/html,text/plain,application/xhtml+xml,application/xml,*/*;q=0.8",
        "Accept-Language": "uz,en-US;q=0.9,en;q=0.8,ru;q=0.7",
    }
    try:
        r = client.get(url, headers=headers, follow_redirects=True, timeout=9.0)
        ctype = r.headers.get("content-type", "").lower()
        if r.status_code >= 400:
            return ""
        if not any(x in ctype for x in ("text", "html", "xml", "json")):
            return ""
        text = r.text[:320_000]
        return normalize_text(strip_tags(text))
    except Exception:
        return ""

def verified_overlap(client: httpx.Client, item: dict, phrase: str) -> tuple[float, str, bool, str]:
    """Return score, snippet, exact flag, evidence type."""
    phrase_norm = normalize_text(phrase)
    snippet = item.get("snippet", "") or item.get("title", "") or ""
    snippet_norm = normalize_text(snippet)

    if phrase_norm and phrase_norm in snippet_norm:
        return 0.98, snippet or phrase, True, "exact phrase in search text"

    ov = overlap_pct(snippet, phrase)
    # Academic services are metadata-based; do not over-score unless overlap is high.
    category = item.get("category") or category_for_url(item.get("url", ""), item.get("provider", ""))
    if category == "academic" and ov >= 0.55:
        return ov, snippet, False, "academic metadata match"

    url = clean_url(item.get("url", ""))
    if url.startswith(("http://", "https://")):
        page_text = fetch_page_text(client, url)
        if page_text:
            if phrase_norm and phrase_norm in page_text:
                return 0.99, snippet or phrase, True, "exact phrase on source page"
            page_ov = overlap_pct(page_text[:18000], phrase)
            ov = max(ov, page_ov)
            if page_ov >= 0.60:
                return ov, snippet or page_text[:300], False, "source page word-overlap"

    return ov, snippet, False, "search snippet word-overlap"

def internet_sources(text: str, max_phrases: int = 6, provider_override: Optional[str] = None) -> dict:
    phrases = pick_query_phrases(text, min(max_phrases, 4))
    if not phrases:
        return {
            "ok": True,
            "provider": "Internet Server",
            "sources": [],
            "onlinePlag": 0,
            "online_plag": 0,
            "phrasesChecked": 0,
            "phrases_checked": 0,
            "notice": "Matn juda qisqa. Internet manbani aniq topish uchun kamida 2–3 to‘liq gap kiriting.",
        }

    by_url: dict[str, dict] = {}
    phrases_with_hit = 0
    exact_hits = 0
    errors: list[str] = []
    total_queries = 0

    with httpx.Client(timeout=16.0, follow_redirects=True) as client:
        for idx, phrase in enumerate(phrases):
            phrase_hits_for_this_phrase = False
            query_pack = [
                ("web", f'"{phrase}"'),
                ("web", phrase),
            ]
            for category, query in query_pack:
                total_queries += 1
                try:
                    items = combined_web_search(client, query, include_extra=True)
                except Exception as exc:
                    errors.append(str(exc)); items = []
                for item in items:
                    url = clean_url(item.get("url", ""))
                    if not url.startswith(("http://", "https://")):
                        continue
                    ov, snippet, exact, evidence = verified_overlap(client, item, phrase)
                    # Correctness rule: exact phrase is strongest; otherwise require high overlap.
                    if not exact and ov < (0.34 if (item.get("provider", "").startswith("Jina")) else 0.50):
                        continue
                    phrase_hits_for_this_phrase = True
                    cat = item.get("category") or category_for_url(url, item.get("provider", ""))
                    if url not in by_url:
                        by_url[url] = {
                            "url": url,
                            "title": item.get("title") or domain_of(url) or url,
                            "domain": item.get("domain") or domain_of(url),
                            "snippet": snippet,
                            "provider": item.get("provider") or "Internet Server",
                            "category": cat,
                            "phrases": 0,
                            "exact": 0,
                            "best": 0.0,
                            "matched_fragment": phrase,
                            "evidence": evidence,
                        }
                    by_url[url]["phrases"] += 1
                    by_url[url]["exact"] += 1 if exact else 0
                    by_url[url]["best"] = max(by_url[url]["best"], ov)
                    if exact:
                        exact_hits += 1

            # Academic repositories and university domains are checked separately,
            # but to keep the desktop app responsive we use fewer phrases here.
            if idx < 4:
                for category, items_fn in (("academic", academic_search), ("university", university_search)):
                    total_queries += 1
                    try:
                        items = items_fn(client, phrase)
                    except Exception as exc:
                        errors.append(str(exc)); items = []
                    for item in items:
                        url = clean_url(item.get("url", ""))
                        if not url.startswith(("http://", "https://")):
                            continue
                        ov, snippet, exact, evidence = verified_overlap(client, item, phrase)
                        # Metadata sources are useful but should not create false high plagiarism.
                        min_score = 0.40 if category in {"academic", "university"} else 0.50
                        if not exact and ov < min_score:
                            continue
                        phrase_hits_for_this_phrase = True
                        if url not in by_url:
                            by_url[url] = {
                                "url": url,
                                "title": item.get("title") or domain_of(url) or url,
                                "domain": item.get("domain") or domain_of(url),
                                "snippet": snippet,
                                "provider": item.get("provider") or category.title(),
                                "category": category,
                                "phrases": 0,
                                "exact": 0,
                                "best": 0.0,
                                "matched_fragment": phrase,
                                "evidence": evidence,
                            }
                        by_url[url]["phrases"] += 1
                        by_url[url]["exact"] += 1 if exact else 0
                        by_url[url]["best"] = max(by_url[url]["best"], ov)
                        if exact:
                            exact_hits += 1

            if phrase_hits_for_this_phrase:
                phrases_with_hit += 1

            # Be polite with public services.
            time.sleep(0.05)

    sources = []
    category_counts = {"web": 0, "academic": 0, "university": 0}
    for s in by_url.values():
        cat = s.get("category") or category_for_url(s["url"], s.get("provider", ""))
        category_counts[cat] = category_counts.get(cat, 0) + 1
        sources.append({
            "url": s["url"],
            "title": s["title"],
            "domain": s["domain"],
            "snippet": s["snippet"],
            "provider": s["provider"],
            "category": cat,
            "matched_fragment": s["matched_fragment"],
            "evidence": s["evidence"],
            "phrases": s["phrases"],
            "exact": s["exact"],
            "strength": source_strength(s["best"], s["phrases"], s["exact"], cat),
        })
    sources.sort(key=lambda x: (x["strength"], x.get("exact", 0), x.get("phrases", 0)), reverse=True)

    # More conservative score: exact phrase/page matches count higher than weak metadata hits.
    if not phrases:
        online_plag = 0
    else:
        phrase_ratio = phrases_with_hit / len(phrases)
        exact_bonus = min(0.25, exact_hits / max(1, len(phrases)) * 0.12)
        online_plag = round(min(100, (phrase_ratio + exact_bonus) * 100))

    if sources:
        notice = (
            "Internet Server Edition: automatic web search, academic metadata, and university-domain searches completed. "
            "Only real source links are shown; exact source text should still be checked by opening each link."
        )
    elif errors:
        notice = "Internet qidiruvi real havola topmadi yoki ayrim qidiruv serverlari blokladi. Internet aloqasini tekshiring va matndan uzunroq, noyobroq parcha kiriting."
    else:
        notice = "Tekshirilgan iboralar bo‘yicha ochiq web, ilmiy va universitet manbalaridan real havola topilmadi."

    return {
        "ok": True,
        "provider": "Internet Server: Web + Academic + University",
        "sources": sources[:20],
        "onlinePlag": online_plag,
        "online_plag": online_plag,
        "phrasesChecked": len(phrases),
        "phrases_checked": len(phrases),
        "phrases": phrases,
        "categoryCounts": category_counts,
        "totalQueries": total_queries,
        "errors": errors[:3],
        "notice": notice,
    }

# --------------------------------------------------------------------------- #
# Application endpoints
# --------------------------------------------------------------------------- #
@app.post("/api/search-sources")
def search_sources_api(req: SearchSourcesRequest):
    return internet_sources(req.text, req.max_phrases, req.provider)

@app.post("/api/extract")
async def extract(file: UploadFile = File(...)):
    raise HTTPException(501, "Server-side extraction is not configured. The browser performs extraction client-side by default.")

def grade_for(score: float) -> str:
    if score >= 90: return "Excellent"
    if score >= 80: return "Good"
    if score >= 60: return "Satisfactory"
    return "Unsatisfactory"

@app.post("/api/analyze", response_model=AnalyzeResponse)
def analyze(req: AnalyzeRequest, user: dict = Depends(current_user_optional)):
    text = req.text or ""
    wc = len(words(text))
    sources_payload = internet_sources(text, 6) if req.online else {"sources": [], "onlinePlag": 0}
    plag = float(sources_payload.get("onlinePlag", 0))
    originality = max(0.0, 100.0 - plag)
    scores = {"spelling": 100, "grammar": 100, "style": 100, "originality": originality, "final": originality}
    notice = str(sources_payload.get("notice", ""))
    return AnalyzeResponse(
        language=req.language or "auto",
        word_count=wc,
        char_count=len(text),
        scores=scores,
        grade=grade_for(scores["final"]),
        ai_probability=0.0,
        human_probability=100.0,
        plagiarism=plag,
        originality=originality,
        issues=[],
        sources=sources_payload.get("sources", []),
        notice=notice,
    )

@app.post("/api/reports")
def save_report(payload: dict, user: dict = Depends(current_user_optional)):
    payload["id"] = secrets.token_hex(8)
    payload["owner"] = user["email"]
    payload["created_at"] = dt.datetime.utcnow().isoformat()
    return {"ok": True, "id": payload["id"]}

@app.get("/api/health")
def health():
    return {
        "status": "ok",
        "mode": "Internet Server Edition",
        "source_groups": ["Jina Reader Search", "open web", "academic repositories", "university domains"],
        "index_html": INDEX_HTML.exists(),
    }

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host="127.0.0.1", port=8000, reload=True)
