"""Bounded local retrieval + optional fixed-provider external search.

Local retrieval is lexical char-ngram scoring, not pretrained semantic embedding.
The runtime can instead select the neural embedding/pgvector adapter in vector.py.
"""
from __future__ import annotations

import re
from collections import Counter
from datetime import UTC, datetime
from math import sqrt

import httpx

from .store import LocalStore


def terms(value: str) -> Counter[str]:
    text = value.lower()
    counts: Counter[str] = Counter(re.findall(r"[a-z0-9_]{2,}", text))
    for sequence in re.findall(r"[\u4e00-\u9fff]+", text):
        counts.update(sequence[i:i + 2] for i in range(max(0, len(sequence) - 1)))
        if len(sequence) == 1:
            counts.update([sequence])
    return counts


def overlap_score(question: str, passage: str) -> float:
    """Local DEMO similarity: lexical n-gram cosine, not neural embeddings."""
    left, right = terms(question), terms(passage)
    if not left or not right:
        return 0.0
    dot = sum(count * right.get(term, 0) for term, count in left.items())
    norm_left = sqrt(sum(count ** 2 for count in left.values()))
    norm_right = sqrt(sum(count ** 2 for count in right.values()))
    return dot / (norm_left * norm_right)


class LocalSearch:
    def __init__(self, store: LocalStore):
        self.store = store

    def search(self, query: str, limit: int = 5) -> list[dict]:
        scored = [(overlap_score(query, item["content"]), item)
                  for item in self.store.list_chunks()]
        scored.sort(key=lambda item: item[0], reverse=True)
        timestamp = datetime.now(UTC).isoformat()
        return [{
            "title": item["title"], "locator": f"local:{item['chunk_id']}",
            "excerpt": item["content"][:900], "source_type": "local",
            "retrieved_at": timestamp, "query": query,
            "document_id": item["doc_id"], "chunk_id": item["chunk_id"],
            "source_ref": item["source_ref"], "score": score,
        } for score, item in scored[:limit] if score > 0]


class NoExternalSearch:
    def search(self, query: str, limit: int = 5) -> list[dict]:
        return []


class TavilySearch:
    """Fixed API endpoint, bounded response. No arbitrary URL fetching."""
    ENDPOINT = "https://api.tavily.com/search"

    def __init__(self, api_key: str):
        self.api_key = api_key

    def search(self, query: str, limit: int = 5) -> list[dict]:
        with httpx.Client(timeout=httpx.Timeout(8.0, connect=3.0), follow_redirects=False,
                          trust_env=False) as client:
            response = client.post(self.ENDPOINT, json={
                "api_key": self.api_key, "query": query[:400],
                "max_results": min(limit, 5), "search_depth": "basic",
            })
            response.raise_for_status()
            payload = response.json()
        if not isinstance(payload, dict) or not isinstance(payload.get("results"), list):
            raise TypeError("SEARCH_RESPONSE_INVALID")
        results = []
        timestamp = datetime.now(UTC).isoformat()
        for item in payload["results"][:limit]:
            if not isinstance(item, dict):
                continue
            url = str(item.get("url", ""))[:500]
            if not url.startswith(("https://", "http://")):
                continue
            results.append({
                "title": str(item.get("title", "Untitled"))[:160],
                "locator": url,
                "excerpt": str(item.get("content", ""))[:900],
                "source_type": "external", "retrieved_at": timestamp, "query": query,
            })
        return results


class SearchTools:
    def __init__(self, local: LocalSearch, external: NoExternalSearch | TavilySearch, top_k: int = 5):
        self.local = local
        self.external = external
        self.top_k = top_k

    def search(self, queries: list[str], source_limit: int = 10) -> tuple[list[dict], list[str]]:
        seen: set[str] = set()
        out: list[dict] = []
        errors: list[str] = []
        for query in queries[:3]:
            for name, provider in (("local", self.local), ("external", self.external)):
                try:
                    items = provider.search(query[:400], limit=min(self.top_k, source_limit))
                except (httpx.HTTPError, ValueError, TypeError) as exc:
                    if name == "local":
                        raise RuntimeError("LOCAL_RETRIEVAL_FAILED") from None
                    # Never dump the exception (can include URL/query/user data).
                    errors.append(f"{name}:SEARCH_FAILED:{type(exc).__name__}")
                    continue
                for item in items:
                    unique = f"{item['locator']}:{item['excerpt']}"
                    if unique in seen or not item["excerpt"].strip():
                        continue
                    seen.add(unique)
                    out.append(item)
                    if len(out) >= source_limit:
                        return out, errors
        return out, errors
