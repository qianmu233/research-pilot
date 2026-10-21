"""Verify local manifests/blobs and measure one cold local generation. No keys."""
import hashlib
import json
import subprocess
import time
from pathlib import Path

import httpx

MODEL = "qwen3:4b-instruct-2507-q4_K_M"


def main():
    output = Path("data/phase7/model-identity.json")
    if output.exists():
        raise RuntimeError("DO_NOT_OVERWRITE_MODEL_IDENTITY")
    with httpx.Client(base_url="http://127.0.0.1:11434", timeout=120, trust_env=False) as client:
        version = client.get("/api/version").json()
        tag = next(item for item in client.get("/api/tags").json()["models"] if item["name"] == MODEL)
        assert tag["digest"].startswith("0edcdef34593")
        show = client.post("/api/show", json={"model": MODEL}).json()
        assert "Apache License" in show["license"] and not show.get("remote_host")
        path = Path("data/ollama-models/manifests/registry.ollama.ai/library/qwen3/4b-instruct-2507-q4_K_M")
        raw = path.read_bytes()
        manifest = json.loads(raw)
        # Ollama 0.40 stores a wrapper retaining the original registry manifest
        # as a layer. API digest identifies that original, not the wrapper bytes.
        original_layer = next(layer for layer in manifest["layers"]
            if layer["mediaType"] == "application/vnd.docker.distribution.manifest.v2+json")
        assert original_layer["digest"].removeprefix("sha256:") == tag["digest"].removeprefix("sha256:")
        original_path = Path("data/ollama-models/blobs") / original_layer["digest"].replace(":", "-")
        original = json.loads(original_path.read_bytes())
        assert original["config"] == manifest["config"]
        assert original["layers"] == [layer for layer in manifest["layers"] if layer != original_layer]
        layers = [manifest["config"], *manifest["layers"]]
        verified = []
        for layer in layers:
            blob = Path("data/ollama-models/blobs") / layer["digest"].replace(":", "-")
            with blob.open("rb") as f:
                actual = hashlib.file_digest(f, "sha256").hexdigest()
            assert "sha256:" + actual == layer["digest"]
            verified.append({**layer, "verified": True})
        started = time.monotonic()
        response = client.post("/api/generate", json={"model": MODEL, "prompt": "请用中文简述数据库事务。",
            "stream": False, "think": False,
            "options": {"num_ctx": 4096, "num_predict": 80, "temperature": 0}})
        response.raise_for_status()
        cold_http_seconds = time.monotonic() - started
        generation = response.json()
        running = client.get("/api/ps").json()
        hardware = subprocess.run(["nvidia-smi", "--query-gpu=name,memory.total,memory.used,memory.free",
            "--format=csv,noheader"], capture_output=True, text=True, check=True).stdout.strip()
        record = {"version": version, "tag": tag, "details": show["details"],
            "model_info": show.get("model_info", {}), "parameters": show.get("parameters", ""),
            "license": show["license"], "template": show.get("template", ""),
            "local_wrapper_sha256": hashlib.sha256(raw).hexdigest(),
            "verified_layers": verified, "generation": generation, "running": running,
            "cold_http_seconds": round(cold_http_seconds, 4), "gpu_after": hardware}
        output.write_text(json.dumps(record, ensure_ascii=False, indent=2), "utf-8")
        print(json.dumps({"version": version, "tag": tag, "running": running,
                          "cold_http_seconds": record["cold_http_seconds"], "gpu_after": hardware}, indent=2))


if __name__ == "__main__":
    main()
