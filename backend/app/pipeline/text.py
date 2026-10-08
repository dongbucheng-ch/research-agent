"""Text normalization helpers for deduplication, language and cleaning."""

from __future__ import annotations

import hashlib
import re
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

TRACKING_PARAMS = {
    "utm_source",
    "utm_medium",
    "utm_campaign",
    "utm_term",
    "utm_content",
    "utm_id",
    "fbclid",
    "gclid",
    "yclid",
    "mc_cid",
    "mc_eid",
    "igshid",
    "spm",
    "ref_src",
    "ref_url",
}

_CJK_RE = re.compile(r"[\u4e00-\u9fff]")
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")
_NON_WORD_RE = re.compile(r"[^\w\u4e00-\u9fff]+")
_WORD_RE = re.compile(r"[a-zA-Z0-9]+")


def normalize_url(url: str) -> str:
    """Canonicalize a URL for deduplication (drop tracking params, sort query)."""
    raw = (url or "").strip()
    if not raw:
        return ""
    try:
        parts = urlsplit(raw)
    except ValueError:
        return raw
    scheme = (parts.scheme or "https").lower()
    netloc = parts.netloc.lower()
    if netloc.startswith("www."):
        netloc = netloc[4:]
    path = parts.path.rstrip("/") or "/"
    query = [
        (k, v)
        for k, v in parse_qsl(parts.query, keep_blank_values=False)
        if k.lower() not in TRACKING_PARAMS
    ]
    query.sort()
    return urlunsplit((scheme, netloc, path, urlencode(query), ""))


def sha256_hex(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def title_fingerprint(title: str) -> str:
    normalized = _WS_RE.sub(" ", _NON_WORD_RE.sub(" ", (title or "").lower())).strip()
    return hashlib.sha1(normalized.encode("utf-8")).hexdigest()


def _tokens(text: str) -> list[str]:
    tokens = _WORD_RE.findall((text or "").lower())
    cjk = _CJK_RE.findall(text or "")
    tokens.extend("".join(pair) for pair in zip(cjk, cjk[1:], strict=False))
    return tokens


def simhash64(text: str) -> str:
    """64-bit SimHash rendered as 16 hex chars (for near-duplicate detection)."""
    tokens = _tokens(text)[:400]
    if not tokens:
        return "0" * 16
    vector = [0] * 64
    for token in tokens:
        digest = int.from_bytes(hashlib.md5(token.encode("utf-8")).digest()[:8], "big")
        for bit in range(64):
            vector[bit] += 1 if (digest >> bit) & 1 else -1
    value = 0
    for bit in range(64):
        if vector[bit] > 0:
            value |= 1 << bit
    return f"{value:016x}"


def hamming_hex(left: str, right: str) -> int:
    return (int(left, 16) ^ int(right, 16)).bit_count()


def strip_html(raw: str) -> str:
    text = _TAG_RE.sub(" ", raw or "")
    text = text.replace("&nbsp;", " ").replace("&amp;", "&").replace("&#39;", "'")
    text = text.replace("&quot;", '"').replace("&lt;", "<").replace("&gt;", ">")
    return _WS_RE.sub(" ", text).strip()


def detect_lang(text: str) -> str:
    sample = (text or "")[:500]
    if not sample.strip():
        return "unknown"
    cjk = len(_CJK_RE.findall(sample))
    return "zh" if cjk >= max(4, len(sample) * 0.05) else "en"


def truncate(text: str, limit: int) -> str:
    text = text or ""
    return text if len(text) <= limit else text[: limit - 1] + "…"
