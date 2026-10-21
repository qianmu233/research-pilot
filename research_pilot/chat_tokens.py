"""Offline, hash-verified Qwen tokenizer; never downloads at application startup."""
import hashlib
import json
from functools import lru_cache
from pathlib import Path


@lru_cache(maxsize=4)
def qwen_tokenizer(cache_dir: Path):
    from tokenizers import Tokenizer
    manifest = json.loads(Path(__file__).with_name("chat-tokenizer.lock.json").read_text("utf-8"))
    directory = cache_dir / ("models--" + manifest["model"].replace("/", "--")) / "snapshots" / manifest["revision"]
    for item in manifest["files"]:
        raw = (directory / item["file"]).read_bytes()
        if hashlib.sha256(raw).hexdigest() != item["sha256"]:
            raise ValueError("CHAT_TOKENIZER_HASH_MISMATCH")
    return Tokenizer.from_file(str(directory / "tokenizer.json"))


def count_qwen_messages(cache_dir: Path, system: str, user: str) -> int:
    # Exact official non-thinking template for this two-message, no-tools path.
    text = (f"<|im_start|>system\n{system}<|im_end|>\n"
            f"<|im_start|>user\n{user}<|im_end|>\n<|im_start|>assistant\n")
    return len(qwen_tokenizer(cache_dir).encode(text, add_special_tokens=False).ids)
