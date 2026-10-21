"""Explicit real, free local Qwen tests. Run separately from tests/.

Requires the approved Ollama/model, both pinned tokenizers, and real PostgreSQL.
There is no skip, simulated provider, lexical fallback, or paid endpoint here.
"""
import hashlib
import json
import os
import socket
import subprocess
import sys
import time
import uuid
from contextlib import contextmanager
from pathlib import Path

import httpx
import pytest

from research_pilot.chat_tokens import qwen_tokenizer
from research_pilot.config import Settings
from research_pilot.local_llm import ContextBudgetExceeded, LocalStructuredModel
from research_pilot.runtime import ResearchRuntime
from research_pilot.schema import CreateTask

ROOT = Path(__file__).resolve().parents[1]
assert hashlib.sha256((ROOT / "benchmarks/local_llm_v1/dataset.json").read_bytes()).hexdigest() == (
    ROOT / "benchmarks/local_llm_v1/dataset.sha256").read_text("utf-8").strip()
DATASET = json.loads((ROOT / "benchmarks/local_llm_v1/dataset.json").read_text("utf-8"))
MODEL = "qwen3:4b-instruct-2507-q4_K_M"
DSN = "postgresql://researchpilot_demo:researchpilot_local_demo@127.0.0.1:15432/researchpilot_demo"
RUN = ROOT / "data/phase7" / os.getenv("RESEARCH_REAL_RUN_LABEL", "real-" + uuid.uuid4().hex[:10])
RUN.mkdir(parents=True, exist_ok=True)


def save(name, value):
    path = RUN / f"{name}.json"
    assert not path.exists(), "Do not overwrite a previous real run"
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2), "utf-8")


@contextmanager
def server(data_dir, collection, top_k):
    data_dir.mkdir(parents=True, exist_ok=True)
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    env = os.environ.copy()
    # Never pass an ambient provider key or tracing configuration to this server.
    for key in list(env):
        if "API_KEY" in key or key.startswith(("LANGSMITH_", "LANGCHAIN_", "RESEARCH_")):
            env.pop(key)
    env.update(RESEARCH_DATA_DIR=str(data_dir), RESEARCH_MODEL_BACKEND="ollama",
        RESEARCH_OPENAI_MODEL=MODEL, RESEARCH_OPENAI_BASE_URL="http://127.0.0.1:11434/v1",
        RESEARCH_RETRIEVAL_BACKEND="pgvector", RESEARCH_POSTGRES_DSN=DSN,
        RESEARCH_EMBEDDING_MODEL="BAAI/bge-small-zh-v1.5",
        RESEARCH_EMBEDDING_CACHE_DIR=str(ROOT / "data/models"),
        RESEARCH_VECTOR_COLLECTION=collection, RESEARCH_RETRIEVAL_TOP_K=str(top_k),
        RESEARCH_MAX_SOURCES="6", RESEARCH_MAX_ROUNDS="3", RESEARCH_MAX_MODEL_CALLS="5",
        RESEARCH_STEP_TIMEOUT_SECONDS="90", RESEARCH_TASK_TIMEOUT_SECONDS="300",
        LANGSMITH_TRACING="false", LANGCHAIN_TRACING_V2="false", PYTHONUTF8="1")
    with (data_dir / "uvicorn.log").open("a", encoding="utf-8") as log:
        process = subprocess.Popen([sys.executable, "-m", "uvicorn", "research_pilot.api:app",
            "--host", "127.0.0.1", "--port", str(port)], cwd=ROOT, env=env,
            stdout=log, stderr=subprocess.STDOUT,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        try:
            with httpx.Client(base_url=f"http://127.0.0.1:{port}", trust_env=False, timeout=10) as client:
                deadline = time.monotonic() + 45
                while time.monotonic() < deadline:
                    assert process.poll() is None, "Uvicorn failed: see the local test log"
                    try:
                        health = client.get("/health")
                        if health.status_code == 200:
                            assert health.json()["model_backend"] == "ollama"
                            assert health.json()["retrieval_backend"] == "pgvector"
                            assert health.json()["embedding_model"] == "BAAI/bge-small-zh-v1.5"
                            break
                    except httpx.TransportError:
                        pass
                    time.sleep(0.2)
                else:
                    raise AssertionError("Real Uvicorn health timeout")
                yield client
        finally:
            process.terminate()
            try:
                process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait(timeout=5)


def run_case(client, case):
    documents = {item["id"]: item for item in DATASET["documents"]}
    imported = {}
    for name in case["documents"]:
        item = documents[name]
        response = client.post("/api/documents/text", json={k: item[k] for k in ("title", "content", "source_ref")})
        response.raise_for_status()
        imported[name] = response.json()["document_id"]
    started = time.monotonic()
    created = client.post("/api/tasks", json={"question": case["question"]})
    assert created.status_code == 202
    tid = created.json()["task_id"]
    deadline = started + 310
    while time.monotonic() < deadline:
        task = client.get(f"/api/tasks/{tid}").json()
        if task["status"] in {"completed", "failed", "timed_out"}:
            break
        time.sleep(0.2)
    result = {"case": case, "imported": imported, "task": task,
              "elapsed_seconds": round(time.monotonic() - started, 3),
              "trace": client.get(f"/api/tasks/{tid}/trace").json()}
    save(case["id"], result)  # Preserve failed tasks before assertions.
    assert task["status"] == "completed", task["error_code"]
    research = task["research"]
    assert research["report"]["answer_status"] == case["expected_answer_status"]
    assert research["citation_valid"] and not research["facts_verified"]
    assert 3 <= task["model_calls"] <= 5
    assert all(event["status"] == "completed" for event in task["model_events"])
    assert task["trace"][0] == "plan" and task["trace"][-1] == "validate:OK"
    rounds = sum(event.startswith("retrieve:") for event in task["trace"])
    assert case.get("minimum_retrieval_rounds", 1) <= rounds <= 3
    sources = {s["source_id"]: s for s in task["sources"]}
    used_docs = set()
    for claim in research["report"]["claims"]:
        source = sources[claim["source_id"]]
        assert claim["quote"] in source["excerpt"]
        assert source["document_id"] in imported.values()
        assert source["locator"].startswith("pgvector:") and source["chunk_id"]
        assert not source["source_ref"].startswith("synthetic:"), "Synthetic fixtures are not public factual evidence"
        used_docs.add(source["document_id"])
    assert {imported[name] for name in case["required_documents"]} <= used_docs
    if case["id"] == "C":
        assert research["assessments"][0]["sufficient"] is False
        assert research["retrieval_rounds"][1]["new_source_ids"]
    if case["id"] == "D":
        assert research["report"]["claims"] == []
        assert not any(a["sufficient"] for a in research["assessments"])
    if case.get("must_retrieve"):
        assert imported[case["must_retrieve"]] in {s["document_id"] for s in task["sources"]}
    for text in case.get("forbidden_report_text", []):
        assert text not in task["report"]
    report = client.get(f"/api/tasks/{tid}/report")
    assert report.status_code == 200 and report.json()["markdown"] == task["report"]
    assert client.post(f"/api/tasks/{tid}/resume").status_code == 409
    return task, report.json()


def test_real_ollama_chinese_schema_identity_context_and_transport_failures():
    started = time.monotonic()
    with httpx.Client(base_url="http://127.0.0.1:11434", timeout=90, trust_env=False) as client:
        version = client.get("/api/version").json()
        assert version["version"] == "0.40.6"
        tags = client.get("/api/tags").json()
        tag = next(m for m in tags["models"] if m["name"] == MODEL)
        assert tag["digest"].startswith("0edcdef34593")
        show = client.post("/api/show", json={"model": MODEL}).json()
        assert show["details"]["quantization_level"] == "Q4_K_M"
        assert "Apache License" in show["license"] and not show.get("remote_host")
        response = client.post("/v1/chat/completions", json={"model": MODEL, "temperature": 0,
            "reasoning_effort": "none",
            "max_tokens": 80, "messages": [{"role": "user", "content": "请用一句中文解释数据库事务。"}]})
        response.raise_for_status()
        chinese = response.json()
        text = chinese["choices"][0]["message"]["content"]
        assert any("\u4e00" <= c <= "\u9fff" for c in text)
        settings = Settings(model_backend="ollama", model_name=MODEL,
                            model_base_url="http://127.0.0.1:11434/v1")
        model = LocalStructuredModel(settings)
        plan, usage = model.generate("plan", {"question": "如何核实 PostgreSQL 事务的原子性？", "scope": ""}, 60)
        assert plan["queries"] and plan["questions"]
        capped = model.client.invoke([("human", "请写三十句介绍数据库事务的中文句子。")],
                                     extra_body={"max_tokens": 1}, reasoning_effort="none")
        assert capped.usage_metadata["output_tokens"] == 1
        assert capped.response_metadata["finish_reason"] == "length"
        invalid = client.post("/v1/chat/completions", json={"model": "researchpilot-invalid-no-pull",
            "messages": [{"role": "user", "content": "测试无效模型"}]})
        assert invalid.status_code == 404
        timeout_observed = False
        try:
            client.post("/v1/chat/completions", timeout=0.001, json={"model": MODEL,
                "max_tokens": 100, "messages": [{"role": "user", "content": "用中文列举事务特性。"}]})
        except httpx.TimeoutException:
            timeout_observed = True
        assert timeout_observed
        long_text = "上下文边界核验资料。" * 2000
        tokenizer = qwen_tokenizer(Path("data/models"))
        original_tokens = len(tokenizer.encode(long_text, add_special_tokens=False).ids)
        assert original_tokens > 4096
        truncated = client.post("/api/generate", json={"model": MODEL, "prompt": long_text,
            "raw": True, "stream": False, "options": {"num_ctx": 4096, "num_predict": 1, "temperature": 0}})
        truncated.raise_for_status()
        truncation = truncated.json()
        assert 0 < truncation["prompt_eval_count"] <= 4096 < original_tokens
        with pytest.raises(ContextBudgetExceeded):
            model.generate("plan", {"question": long_text, "scope": ""}, 30)
        running = client.get("/api/ps").json()
        assert next(m for m in running["models"] if m["name"] == MODEL)["context_length"] == 4096
        save("environment", {"version": version, "tag": tag, "details": show["details"],
            "chinese": chinese, "plan": plan, "usage": usage,
            "adapter_output_cap": {"usage": capped.usage_metadata, "finish_reason": capped.response_metadata["finish_reason"]},
            "invalid_model_http": invalid.status_code,
            "timeout_observed": timeout_observed, "original_long_tokens": original_tokens,
            "truncation": truncation, "running": running, "elapsed_seconds": time.monotonic() - started})


def test_real_http_single_document_and_restart():
    case = DATASET["tasks"][0]
    directory = RUN / "A-state"
    collection = "phase7-real-A-" + uuid.uuid4().hex[:12]
    with server(directory, collection, case["top_k"]) as client:
        task, report = run_case(client, case)
    with server(directory, collection, case["top_k"]) as client:
        assert client.get(f"/api/tasks/{task['id']}").json() == task
        assert client.get(f"/api/tasks/{task['id']}/report").json() == report


@pytest.mark.parametrize("case", DATASET["tasks"][1:], ids=lambda c: c["id"])
def test_real_http_evidence_quality_cases(case):
    with server(RUN / (case["id"] + "-state"), "phase7-real-" + uuid.uuid4().hex[:12], case["top_k"]) as client:
        run_case(client, case)


def test_real_graph_model_timeout_does_not_publish_report(tmp_path):
    settings = Settings(data_dir=tmp_path, model_backend="ollama", model_name=MODEL,
        model_base_url="http://127.0.0.1:11434/v1", retrieval_backend="pgvector", postgres_dsn=DSN,
        embedding_model="BAAI/bge-small-zh-v1.5", vector_collection="phase7-timeout-" + uuid.uuid4().hex[:12],
        step_timeout_seconds=0.01)
    runtime = ResearchRuntime(settings)
    try:
        task_id = runtime.create_task(CreateTask(question="请解释PostgreSQL事务的原子性，并提供研究计划。"))
        runtime.run_task(task_id)
        task = runtime.get_task(task_id)
        save("F-timeout", task)
        assert task["status"] == "timed_out" and task["report"] is None
        assert task["error_code"] == "WORKFLOW_STEP_TIMEOUT"
        assert task["model_calls"] == 1 and task["model_events"][0]["status"] == "failed"
        assert runtime.graph.get_state({"configurable": {"thread_id": task_id}}).next
    finally:
        runtime.close()
