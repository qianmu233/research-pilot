"""Run the verified portable Ollama, loopback only, without global installation.

Does not download weights. Use --pull only after the user's model confirmation.
"""
import argparse
import hashlib
import json
import os
import subprocess
import time
import zipfile
from pathlib import Path

import httpx
from download_ollama_windows import SHA256, TARGET

MODEL = "qwen3:4b-instruct-2507-q4_K_M"
BASE = "http://127.0.0.1:11434"


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--pull", action="store_true")
    args = parser.parse_args()
    root = Path.cwd().resolve()
    directory = root / "data/tools/ollama-v0.40.6"
    home = root / "data/ollama-home"
    artifacts = root / "data/phase7"
    artifacts.mkdir(parents=True, exist_ok=True)
    with httpx.Client(base_url=BASE, timeout=3, trust_env=False) as client:
        try:
            version = client.get("/api/version")
            version.raise_for_status()
        except httpx.TransportError:
            with TARGET.open("rb") as f:
                if hashlib.file_digest(f, "sha256").hexdigest() != SHA256:
                    raise RuntimeError("UNVERIFIED_OLLAMA_ARCHIVE")
            directory.mkdir(parents=True, exist_ok=True)
            with zipfile.ZipFile(TARGET) as archive:
                for item in archive.infolist():
                    if not (directory / item.filename).resolve().is_relative_to(directory):
                        raise RuntimeError("ARCHIVE_PATH_INVALID")
                archive.extractall(directory)
            home.mkdir(parents=True, exist_ok=True)
            env = {k: os.environ[k] for k in ("PATH", "SystemRoot", "WINDIR", "TEMP", "TMP") if k in os.environ}
            env.update(USERPROFILE=str(home), APPDATA=str(home / "AppData/Roaming"),
                       LOCALAPPDATA=str(home / "AppData/Local"),
                       OLLAMA_HOST="127.0.0.1:11434", OLLAMA_MODELS=str(root / "data/ollama-models"),
                       OLLAMA_NO_CLOUD="1", OLLAMA_CONTEXT_LENGTH="4096", OLLAMA_NUM_PARALLEL="1",
                       OLLAMA_MAX_LOADED_MODELS="1", OLLAMA_FLASH_ATTENTION="1", OLLAMA_KEEP_ALIVE="10m")
            with (artifacts / "ollama-server.log").open("ab") as log:
                process = subprocess.Popen([str(directory / "ollama.exe"), "serve"], cwd=directory,
                    env=env, stdout=log, stderr=subprocess.STDOUT, creationflags=subprocess.CREATE_NO_WINDOW)
            (artifacts / "ollama-process.json").write_text(json.dumps({"pid": process.pid, "base_url": BASE,
                "version": "0.40.6", "context": 4096, "parallel": 1, "cloud_disabled": True}), "utf-8")
            for _ in range(100):
                if process.poll() is not None:
                    raise RuntimeError("OLLAMA_START_FAILED_SEE_LOCAL_LOG")
                try:
                    version = client.get("/api/version")
                    if version.status_code == 200:
                        break
                except httpx.TransportError:
                    pass
                time.sleep(0.2)
            else:
                raise RuntimeError("OLLAMA_HEALTH_TIMEOUT")
        assert version.json()["version"] == "0.40.6", "Unexpected service identity; do not reuse it"
        print("Loopback-only Ollama healthy:", version.json(), flush=True)
    if args.pull:
        with (httpx.Client(base_url=BASE, timeout=httpx.Timeout(90, connect=5), trust_env=False) as client,
              client.stream("POST", "/api/pull", json={"model": MODEL, "stream": True}) as response):
            response.raise_for_status()
            last = ""
            for line in response.iter_lines():
                item = json.loads(line)
                if "error" in item:
                    raise RuntimeError("MODEL_PULL_FAILED")
                label = item.get("status", "")
                if label != last:
                    print(label, flush=True)
                    last = label
        print("Selected single model pull complete", flush=True)


if __name__ == "__main__":
    main()
