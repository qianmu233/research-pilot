"""Download one official fixed Windows archive with resumable verified ranges.

No installer execution. A complete SHA256 match is required before extraction.
"""
import concurrent.futures
import hashlib
import time
from pathlib import Path

import httpx

URL = "https://github.com/ollama/ollama/releases/download/v0.40.6/ollama-windows-amd64.zip"
SHA256 = "e359637575302f288d76c0007c408a4be9c7376d59c4f28684d63b232a44b427"
TOTAL = 1471164488
CHUNK = 4 * 1024 * 1024
TARGET = Path("data/tools/ollama-windows-amd64-v0.40.6-verified.zip")


def main():
    TARGET.parent.mkdir(parents=True, exist_ok=True)
    # A previous official redirect is an optional network fallback. Its contents
    # are never printed; final archive SHA256 is checked regardless of routing.
    try:
        with httpx.Client(timeout=30, follow_redirects=True) as client:
            response = client.head(URL)
            response.raise_for_status()
            resolved = str(response.url)
    except httpx.HTTPError:
        headers = Path("data/phase7/ollama-alternate-headers.txt").read_text()
        resolved = [line.split(": ", 1)[1].strip() for line in headers.splitlines()
                    if line.lower().startswith("location: ")][-1]
    if not resolved.startswith("https://release-assets.githubusercontent.com/"):
        raise RuntimeError("UNEXPECTED_OFFICIAL_ASSET_HOST")
    parts = [(i, start, min(start + CHUNK, TOTAL) - 1)
             for i, start in enumerate(range(0, TOTAL, CHUNK))]
    def fetch(part):
        i, start, end = part
        path = TARGET.with_suffix(f".part{i}")
        if path.exists() and path.stat().st_size == end - start + 1:
            return
        for attempt in range(3):
            try:
                with httpx.Client(timeout=60) as client:
                    r = client.get(resolved, headers={"Range": f"bytes={start}-{end}",
                                                      "Accept-Encoding": "identity"})
                    r.raise_for_status()
                    if (r.status_code != 206 or len(r.content) != end - start + 1 or
                            r.headers.get("Content-Range") != f"bytes {start}-{end}/{TOTAL}"):
                        raise RuntimeError("DOWNLOAD_RANGE_INVALID")
                    path.write_bytes(r.content)
                    return
            except httpx.HTTPError:
                if attempt == 2:
                    raise RuntimeError("OFFICIAL_DOWNLOAD_FAILED") from None
                time.sleep(attempt + 1)
    with concurrent.futures.ThreadPoolExecutor(max_workers=32) as pool:
        for i, _ in enumerate(pool.map(fetch, parts), 1):
            if i % 16 == 0 or i == len(parts):
                print(f"Official archive ranges complete: {i}/{len(parts)}", flush=True)
    digest = hashlib.sha256()
    with TARGET.open("wb") as target:
        for i, _, _ in parts:
            raw = TARGET.with_suffix(f".part{i}").read_bytes()
            digest.update(raw)
            target.write(raw)
    if digest.hexdigest() != SHA256:
        raise RuntimeError("OFFICIAL_ARCHIVE_HASH_MISMATCH")
    for i, _, _ in parts:
        TARGET.with_suffix(f".part{i}").unlink()
    print(f"Verified Ollama 0.40.6: {TARGET} SHA256={SHA256}", flush=True)


if __name__ == "__main__":
    main()
