"""Explicitly fetch only the pinned Qwen tokenizer/config/license, never weights."""
import hashlib
import json
from pathlib import Path

from huggingface_hub import hf_hub_download


def main():
    manifest = json.loads(Path("research_pilot/chat-tokenizer.lock.json").read_text("utf-8"))
    for item in manifest["files"]:
        path = hf_hub_download(manifest["model"], item["file"], revision=manifest["revision"],
                               cache_dir="data/models", token=False)
        assert hashlib.sha256(Path(path).read_bytes()).hexdigest() == item["sha256"]
    print("Pinned official Qwen tokenizer and license verified; no weights downloaded.")


if __name__ == "__main__":
    main()
