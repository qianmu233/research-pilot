"""Offline model TCP + real loopback FastAPI/BGE/PgVector, never paid DeepSeek."""
import json
import time
import uuid
from dataclasses import replace

import httpx
import pytest
from test_deepseek_contracts import LoopbackTransport
from test_deepseek_contracts import provider as provider_fixture

from scripts import deepseek_http_a as experiment

provider = provider_fixture


def test_dry_run_no_settings_or_network(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["preview"])
    def forbidden(*args, **kwargs):
        raise AssertionError("No configuration/network in dry run")
    monkeypatch.setattr("research_pilot.config.Settings.from_env", forbidden)
    monkeypatch.setattr(httpx.Client, "send", forbidden)
    assert experiment.main() == 0
    result = json.loads(capsys.readouterr().out)
    assert result["max_http_attempts"] == 5 and result["estimated_max_usd"] < .02


def test_transport_attempt_budget_failure_and_input_gate(tmp_path):
    calls = []
    def reply(request):
        calls.append(request)
        return httpx.Response(200, json={"usage": {"prompt_tokens": 100,
                                                   "completion_tokens": 10, "total_tokens": 110}})
    gate = experiment.RequestGate(tmp_path, httpx.MockTransport(reply))
    gate.deadline = time.monotonic() + 10
    body = {"model": "deepseek-flash", "max_tokens": 768, "temperature": 0,
            "thinking": {"type": "disabled"}, "response_format": {"type": "json_object"},
            "messages": [{"role": "system", "content": "JSON"},
                         {"role": "user", "content": json.dumps({
                             "question": experiment.PUBLIC_QUESTION})}]}
    def send(value=body):
        return gate.handle_request(httpx.Request("POST", "https://api.deepseek.com/chat/completions",
                                                 json=value))
    with pytest.raises(RuntimeError, match="INPUT_BUDGET"):
        send({**body, "messages": [{"role": "system", "content": "x"*8200}, body["messages"][1]]})
    assert not calls and not gate.events
    for _ in range(5):
        send()
    with pytest.raises(RuntimeError, match="BUDGET_OR_DEADLINE"):
        send()
    assert len(calls) == 5 and len(gate.events) == 5
    saved = json.loads((tmp_path / "http-attempts.json").read_text())
    assert saved["http_attempts"] == 5
    assert "Authorization" not in json.dumps(saved)
    # Failed requests consume a slot; unknown usage also forbids another request.
    for index, status in enumerate((401, 200)):
        directory = tmp_path / str(index)
        directory.mkdir()
        reached = []
        def failed_response(request, status=status, reached=reached):
            reached.append(True)
            return httpx.Response(status, json={})
        gate = experiment.RequestGate(directory, httpx.MockTransport(failed_response))
        gate.deadline = time.monotonic() + 10
        send()
        with pytest.raises(RuntimeError, match="BUDGET_OR_DEADLINE"):
            send()
        assert len(gate.events) == len(reached) == 1 and gate.blocked_reason


@pytest.mark.parametrize("fail", [False, True])
def test_actual_http_graph_vector_and_restart_offline(provider, tmp_path, fail):
    settings, _, scripted, requests, server = provider
    settings = replace(settings, data_dir=tmp_path, postgres_dsn=experiment.DEMO_DSN,
        retrieval_backend="pgvector", embedding_model="BAAI/bge-small-zh-v1.5",
        embedding_cache_dir=experiment.ROOT / "data/models", model_context_tokens=8192,
        model_output_tokens=768, retrieval_top_k=1,
        vector_collection="phase73-contract-" + uuid.uuid4().hex)
    if fail:
        scripted.append({"http": 401})
    else:
        scripted.extend([
            {"value": {"objective": "核对合成演示笔记", "questions": [experiment.PUBLIC_QUESTION],
                       "queries": ["演示组件 检查点 保存 图状态"]}},
            {"value": {"sufficient": True, "reason": "笔记直接支持", "source_ids": ["S1"],
                       "missing_information": [], "next_queries": []}},
            {"value": {"title": "公开合成演示报告", "answer_status": "answered", "claims": [
                {"text": "演示组件通过检查点保存单个线程的图状态。", "source_id": "S1",
                 "quote": "演示组件通过检查点保存单个线程的图状态。"}],
                "limitations": ["仅据公开合成资料，未经外部事实核验。"]}}])
    result = experiment.execute(settings, tmp_path, inner=LoopbackTransport(server.server_port))
    expected = 1 if fail else 3
    assert result["http_attempts"] == len(requests) == expected
    assert result["status"] == ("failed" if fail else "completed"), result
    assert result["error_code"] == ("MODEL_AUTHENTICATION_FAILED" if fail else None)
    restart = json.loads((tmp_path / "restart.json").read_text())
    assert restart["same_task_report_trace"] is True
    assert restart["http_attempts_before"] == restart["http_attempts_after"] == expected
    task = json.loads((tmp_path / "A.json").read_text("utf-8"))
    assert task["model_calls"] == expected
    if not fail:
        assert all(result["checks"].values())
        assert task["trace"] == ["plan", "retrieve:1:1", "assess:model_sufficient", "write", "validate:OK"]
        assert [e["stage"] for e in task["model_events"]] == ["plan", "assess", "write"]
        assert task["research"]["facts_verified"] is False
        assert result["estimated_cost_usd"] == .0000639
    else:
        assert task["report"] is None and result["estimated_cost_usd"] is None
