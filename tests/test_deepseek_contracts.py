"""Real SDK + local TCP provider + real graph/SQLite. NOT real DeepSeek quality."""
import json
import socket
import threading
import time
from collections import deque
from contextlib import ExitStack
from dataclasses import replace
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import httpx
import pytest
from langchain_openai import ChatOpenAI

from research_pilot.config import Settings
from research_pilot.deepseek import DeepSeekStructuredModel
from research_pilot.local_llm import LocalStructuredModel, ProviderFailure
from research_pilot.runtime import ResearchRuntime
from research_pilot.schema import CreateTask, IngestText

PLAN = {"objective": "核对公开合成资料", "questions": ["checkpoint是什么"], "queries": ["checkpoint"]}
ASSESS = {"sufficient": True, "reason": "资料直接说明checkpoint", "source_ids": ["S1"],
          "missing_information": [], "next_queries": []}
QUOTE = "checkpoint 保存图状态。"
REPORT = {"title": "合成协议报告", "answer_status": "answered", "claims": [
    {"text": "checkpoint保存状态", "source_id": "S1", "quote": QUOTE}], "limitations": ["未经事实验证"]}
SOURCES = [{"source_id": "S1", "title": "明确标记的公开合成测试材料", "excerpt": QUOTE,
            "source_ref": "synthetic:phase72-contract"}]


class LoopbackTransport(httpx.BaseTransport):
    """DNS/network fail-closed: only the test's local TCP listener is contacted."""
    def __init__(self, port):
        self.port, self.inner = port, httpx.HTTPTransport(retries=0)

    def handle_request(self, request):
        assert request.url.host == "api.deepseek.com"
        url = request.url.copy_with(scheme="http", host="127.0.0.1", port=self.port)
        return self.inner.handle_request(httpx.Request(request.method, url,
            content=request.content, headers=request.headers, extensions=request.extensions))

    def close(self):
        self.inner.close()


@pytest.fixture
def provider(tmp_path, monkeypatch):
    monkeypatch.setenv("LANGSMITH_TRACING", "false")
    monkeypatch.setenv("LANGCHAIN_TRACING_V2", "false")
    script, requests = deque(), []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass  # Never log headers, bodies or keys, even for a simulated provider.

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            assert self.path in {"/chat/completions", "/v1/chat/completions"}
            # Synthetic test credential only; do not retain the header.
            assert self.headers.get("Authorization") == "Bearer contract-no-secret"
            requests.append(body)
            item = script.popleft() if script else {"http": 500}
            if callable(item):
                item = item(body)
            if item.get("disconnect"):
                self.connection.shutdown(socket.SHUT_RDWR)
                self.connection.close()
                return
            time.sleep(item.get("delay", 0))
            status = item.get("http", 200)
            content = item.get("content", json.dumps(item.get("value", PLAN), ensure_ascii=False))
            payload = {"id": "offline-contract", "object": "chat.completion", "created": 0,
                "model": "deepseek-flash-contract-revision", "choices": [{"index": 0,
                    "finish_reason": item.get("finish", "stop"),
                    "message": {"role": "assistant", "content": content}}],
                "usage": {"prompt_tokens": 19, "completion_tokens": 13, "total_tokens": 32}}
            if status != 200:
                payload = {"error": {"message": "Authorization: Bearer SYNTHETIC_DO_NOT_LEAK"}}
            raw = json.dumps(item.get("raw", payload)).encode()
            self.send_response(status)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            try:
                self.wfile.write(raw)
            except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
                pass

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    with ExitStack() as stack:
        settings = Settings(data_dir=tmp_path, model_backend="deepseek", model_name="deepseek-flash",
            model_base_url="https://api.deepseek.com", model_api_key="contract-no-secret",
            model_context_tokens=8192, model_output_tokens=128, max_rounds=3)

        def model(config=settings):
            client = stack.enter_context(httpx.Client(transport=LoopbackTransport(server.server_port),
                                                     trust_env=False, follow_redirects=False))
            return DeepSeekStructuredModel(config, http_client=client)
        yield settings, model, script, requests, server
    server.shutdown()
    server.server_close()
    thread.join(5)


def payload(stage):
    return {"question": "公开合成资料中checkpoint如何保存状态？", "scope": "",
            "plan": PLAN, "assessment": ASSESS, "sources": SOURCES}


@pytest.mark.parametrize("stage,value", [("plan", PLAN), ("assess", ASSESS), ("write", REPORT)])
def test_all_nodes_send_json_object_and_validate_pydantic(provider, stage, value):
    settings, make, script, requests, _ = provider
    script.append({"value": value})
    parsed, usage = make().generate(stage, payload(stage), 2)
    assert parsed == value
    body = requests[0]
    assert body["response_format"] == {"type": "json_object"}
    assert body["model"] == "deepseek-flash" and body["temperature"] == 0
    assert body["max_tokens"] == settings.model_output_tokens
    assert body["thinking"] == {"type": "disabled"}
    assert not {"max_completion_tokens", "tools", "reasoning_effort"} & body.keys()
    assert "JSON_SCHEMA" in body["messages"][0]["content"]
    assert body["messages"][1]["role"] == "user"
    assert usage["provider"] == "deepseek" and usage["response_model"] == "deepseek-flash-contract-revision"
    assert usage["input_tokens"] == 19 and usage["output_tokens"] == 13 and usage["total_tokens"] == 32
    assert usage["finish_reason"] == "stop" and len(requests) == 1


@pytest.mark.parametrize("item,code", [
    ({"content": ""}, "MODEL_EMPTY_RESPONSE"),
    ({"content": "  "}, "MODEL_EMPTY_RESPONSE"),
    ({"content": "not JSON"}, "MODEL_JSON_SCHEMA_INVALID"),
    ({"content": '{"objective": "x"'}, "MODEL_JSON_SCHEMA_INVALID"),
    ({"value": {"objective": "缺少字段"}}, "MODEL_JSON_SCHEMA_INVALID"),
    ({"value": {**PLAN, "unwanted": "field"}}, "MODEL_JSON_SCHEMA_INVALID"),
    ({"value": {**PLAN, "queries": "not a list"}}, "MODEL_JSON_SCHEMA_INVALID"),
    ({"content": "{", "finish": "length"}, "MODEL_OUTPUT_TRUNCATED"),
    ({"value": PLAN, "finish": "content_filter"}, "MODEL_RESPONSE_INVALID"),
    ({"raw": {"choices": []}}, "MODEL_RESPONSE_INVALID"),
])
def test_strict_response_rejection_no_repair_or_retry(provider, item, code):
    _, make, script, requests, _ = provider
    script.append(item)
    with pytest.raises(ProviderFailure) as error:
        make().generate("plan", payload("plan"), 2)
    assert error.value.code == code and len(requests) == 1
    if code != "MODEL_RESPONSE_INVALID":
        assert error.value.usage["input_tokens"] == 19


@pytest.mark.parametrize("status,code", [(401, "MODEL_AUTHENTICATION_FAILED"),
    (403, "MODEL_PERMISSION_DENIED"), (429, "MODEL_RATE_LIMITED"), (500, "MODEL_SERVER_ERROR"),
    (503, "MODEL_SERVER_ERROR")])
def test_http_errors_fail_graph_with_safe_state_and_one_call(provider, status, code, caplog):
    settings, make, script, requests, _ = provider
    script.append({"http": status})
    runtime = ResearchRuntime(settings, model=make())
    try:
        tid = runtime.create_task(CreateTask(question="公开合成研究问题是什么？"))
        runtime.run_task(tid)
        task = runtime.get_task(tid)
        assert task["status"] == "failed" and task["report"] is None and task["error_code"] == code
        assert task["model_calls"] == 1 and task["model_events"][0]["status"] == "failed"
        assert task["model_events"][0]["provider"] == "deepseek"
        assert task["research"]["model"]["provider"] == "deepseek"
        assert runtime.graph.get_state({"configurable": {"thread_id": tid}}).next == ("plan",)
        assert len(requests) == 1
        assert "SYNTHETIC_DO_NOT_LEAK" not in json.dumps(task) + caplog.text
        assert "contract-no-secret" not in json.dumps(task) + caplog.text
    finally:
        runtime.close()


def seed(runtime):
    runtime.ingest_text(IngestText(title="公开合成测试材料", content=QUOTE + " 本文只用于固定协议测试，无企业资料。"))
    return runtime.create_task(CreateTask(question="公开合成资料中checkpoint如何保存图状态？"))


def test_same_graph_success_usage_and_completed_restart(provider):
    settings, make, script, requests, _ = provider
    script.extend([{"value": PLAN}, {"value": ASSESS}, {"value": REPORT}])
    first = ResearchRuntime(settings, model=make())
    tid = seed(first)
    first.run_task(tid)
    task = first.get_task(tid)
    assert task["status"] == "completed" and task["model_calls"] == 3
    assert task["trace"] == ["plan", "retrieve:1:1", "assess:model_sufficient", "write", "validate:OK"]
    assert task["research"]["report"] == REPORT and task["research"]["citation_valid"]
    assert not task["research"]["facts_verified"] and task["evidence_status"] == "unverified"
    assert [e["stage"] for e in task["model_events"]] == ["plan", "assess", "write"]
    assert all(e["input_tokens"] == 19 and e["finish_reason"] == "stop" for e in task["model_events"])
    assert not first.graph.get_state({"configurable": {"thread_id": tid}}).next
    first.close()
    second = ResearchRuntime(settings, model=make())
    try:
        second.run_task(tid)
        assert second.get_task(tid) == task and len(requests) == 3
    finally:
        second.close()


def test_failed_write_resumes_without_provider_swap_or_resetting_calls(provider):
    settings, make, script, requests, _ = provider
    script.extend([{"value": PLAN}, {"value": ASSESS}, {"http": 429}])
    first = ResearchRuntime(settings, model=make())
    tid = seed(first)
    first.run_task(tid)
    before = first.get_task(tid)
    assert before["model_calls"] == 3 and before["error_code"] == "MODEL_RATE_LIMITED"
    assert first.graph.get_state({"configurable": {"thread_id": tid}}).next == ("write",)
    first.close()
    wrong = make()
    wrong.identity = {"provider": "ollama", "model": "qwen-test", "base_url": "http://localhost:11434/v1"}
    changed = ResearchRuntime(settings, model=wrong)
    changed.run_task(tid)
    assert changed.get_task(tid)["error_code"] == "MODEL_IDENTITY_MISMATCH"
    assert changed.get_task(tid)["model_calls"] == 3 and len(requests) == 3
    changed.close()
    script.append({"value": REPORT})
    second = ResearchRuntime(settings, model=make())
    try:
        second.run_task(tid)
        task = second.get_task(tid)
        assert task["status"] == "completed" and task["error_code"] is None
        assert task["model_calls"] == 4 and len(requests) == 4
        assert task["sources"] == before["sources"] and task["research"]["model"] == before["research"]["model"]
        assert [e["status"] for e in task["model_events"]] == ["completed", "completed", "failed", "completed"]
    finally:
        second.close()


def test_budget_and_deadline_survive_reopen(provider):
    settings, make, script, requests, _ = provider
    settings = replace(settings, max_model_calls=3)
    script.extend([{"value": PLAN}, {"value": ASSESS}, {"http": 500}])
    first = ResearchRuntime(settings, model=make(settings))
    tid = seed(first)
    first.run_task(tid)
    first.close()
    second = ResearchRuntime(settings, model=make(settings))
    try:
        second.run_task(tid)
        assert second.get_task(tid)["error_code"] == "WORKFLOW_FAILURE_ModelCallBudgetExceeded"
        assert second.get_task(tid)["model_calls"] == 3 and len(requests) == 3
        with second.store.conn:
            second.store.conn.execute("UPDATE model_budgets SET started=? WHERE task_id=?", (time.time() - 301, tid))
        second.run_task(tid)
        assert second.get_task(tid)["status"] == "timed_out" and second.get_task(tid)["report"] is None
        assert len(requests) == 3
    finally:
        second.close()


def test_three_rounds_five_calls_and_no_answer_with_candidates(provider):
    settings, make, script, requests, _ = provider
    insufficient = {**ASSESS, "sufficient": False, "missing_information": ["资料没有答案"],
                    "next_queries": ["checkpoint"]}
    report = {**REPORT, "answer_status": "insufficient_evidence", "claims": []}
    script.extend([{"value": PLAN}] + [{"value": insufficient}] * 3 + [{"value": report}])
    runtime = ResearchRuntime(settings, model=make())
    try:
        tid = seed(runtime)
        runtime.run_task(tid)
        task = runtime.get_task(tid)
        assert task["status"] == "completed" and len(requests) == task["model_calls"] == 5
        assert len(task["research"]["retrieval_rounds"]) == 3
        assert task["research"]["report"]["claims"] == [] and task["evidence_status"] == "unverified"
    finally:
        runtime.close()


def test_unknown_citation_is_rejected_after_valid_provider_json(provider):
    settings, make, script, _, _ = provider
    bad = {**REPORT, "claims": [{**REPORT["claims"][0], "source_id": "S999"}]}
    script.extend([{"value": PLAN}, {"value": ASSESS}, {"value": bad}])
    runtime = ResearchRuntime(settings, model=make())
    try:
        tid = seed(runtime)
        runtime.run_task(tid)
        task = runtime.get_task(tid)
        assert task["status"] == "failed" and task["report"] is None
        assert task["research"]["validation_reason"] == "UNKNOWN_CITATION_ID"
    finally:
        runtime.close()


def test_real_local_tcp_timeout_and_connection_classification(provider, monkeypatch):
    settings, make, script, requests, _ = provider
    model = make()
    original = model.request
    monkeypatch.setattr(model, "request", lambda a, b, c, d: original(a, b, c, min(d, .03)))
    script.append({"value": PLAN, "delay": .1})
    runtime = ResearchRuntime(settings, model=model)
    try:
        tid = runtime.create_task(CreateTask(question="公开合成资料的研究规划是什么？"))
        runtime.run_task(tid)
        task = runtime.get_task(tid)
        assert task["status"] == "timed_out" and task["error_code"] == "MODEL_TIMEOUT"
        time.sleep(.15)
        assert runtime.get_task(tid) == task and task["report"] is None
        assert len(requests) == 1 and task["model_calls"] == 1
    finally:
        runtime.close()
    script.append({"disconnect": True})
    with pytest.raises(ProviderFailure, match="MODEL_CONNECTION_ERROR"):
        make().generate("plan", payload("plan"), 2)


def test_config_and_factory_keep_explicit_provider_and_cost_limits(provider, monkeypatch):
    settings, make, _, requests, _ = provider
    for changes in [{"model_api_key": ""}, {"model_base_url": "http://api.deepseek.com"},
                    {"model_base_url": "https://example.org"}, {"model_name": "another-model"},
                    {"max_model_calls": 6}, {"task_timeout_seconds": 301}, {"model_output_tokens": 1024}]:
        with pytest.raises(ValueError):
            replace(settings, **changes).validate()
    assert "contract-no-secret" not in repr(settings)
    monkeypatch.setattr("research_pilot.deepseek.DeepSeekStructuredModel", lambda s: make(s))
    runtime = ResearchRuntime(settings)
    assert runtime.model_identity["provider"] == "deepseek" and not requests
    runtime.close()


def test_assessment_types_are_strict_and_budget_guard_sends_nothing(provider):
    _, make, script, requests, _ = provider
    script.append({"value": {**ASSESS, "sufficient": "true"}})
    with pytest.raises(ProviderFailure, match="MODEL_JSON_SCHEMA_INVALID"):
        make().generate("assess", payload("assess"), 2)
    from research_pilot.local_llm import ContextBudgetExceeded
    with pytest.raises(ContextBudgetExceeded):
        make().generate("plan", {"question": "超长公开合成资料" * 2000}, 2)
    assert len(requests) == 1


def test_preview_default_is_dry_run_without_reading_credentials(monkeypatch, capsys):
    from scripts import deepseek_preview
    monkeypatch.setattr("sys.argv", ["deepseek_preview.py"])
    def forbidden():
        raise AssertionError("Dry run must not read settings/credentials or construct a provider")
    monkeypatch.setattr(deepseek_preview.Settings, "from_env", forbidden)
    deepseek_preview.main()
    plan = json.loads(capsys.readouterr().out)
    assert plan["execution"] == "dry_run_no_key_read_no_requests"
    assert plan["smoke"]["max_requests"] == 1 and plan["A"]["max_requests"] == 5
    assert plan["smoke_plus_A"]["estimated_ceiling_usd"] < .03


@pytest.mark.parametrize("stage,value", [("plan", PLAN), ("assess", ASSESS), ("write", REPORT)])
def test_ollama_all_nodes_keep_original_json_schema_wire(provider, stage, value):
    _, _, script, requests, server = provider
    settings = Settings(model_backend="ollama", model_name="local-contract",
                        model_base_url=f"http://127.0.0.1:{server.server_port}/v1")
    model = LocalStructuredModel(settings)  # No identity preflight in this offline transport contract.
    script.append({"value": value})
    with httpx.Client(trust_env=False) as client:
        model.client = ChatOpenAI(model="local-contract", api_key="contract-no-secret",
            base_url=settings.model_base_url, max_retries=0, http_client=client)
        parsed, _ = model.generate(stage, payload(stage), 3)
    assert parsed == value
    assert requests[0]["response_format"]["type"] == "json_schema"
    assert requests[0]["max_tokens"] == 768 and requests[0]["reasoning_effort"] == "none"
    assert "thinking" not in requests[0]
