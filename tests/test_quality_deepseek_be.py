"""B/E public fixtures + real local HTTP/SQLite/BGE/PgVector, scripted model TCP.

No DNS connection to DeepSeek, no real key, no cloud quality claim.
"""
import json
import time
import uuid
from dataclasses import replace

import httpx
import pytest
from test_deepseek_contracts import LoopbackTransport
from test_deepseek_contracts import provider as provider_fixture

from scripts import deepseek_be as be

provider = provider_fixture


def test_be_default_does_not_read_credentials_or_open_network(monkeypatch, capsys):
    monkeypatch.setattr("sys.argv", ["deepseek_be"])

    def forbidden(*args, **kwargs):
        raise AssertionError("Dry run must not load credentials or perform I/O")

    monkeypatch.setattr("research_pilot.config.Settings.from_env", forbidden)
    monkeypatch.setattr(httpx.Client, "send", forbidden)
    original_get = be.os.environ.get

    def no_credentials(name, *args):
        if name == "RESEARCH_OPENAI_API_KEY":
            return forbidden()
        return original_get(name, *args)

    monkeypatch.setattr(be.os.environ, "get", no_credentials)
    assert be.main() == 0
    result = json.loads(capsys.readouterr().out)
    assert result["max_total_requests"] == 10 and result["proposed_budget_usd"] == .04
    from decimal import Decimal
    assert Decimal(str(result["estimated_ceiling_usd"])) == 10 * (8192*Decimal(".3") + 768*Decimal("1.2"))/1000000


def test_be_gate_exact_public_payload_and_failure_ledger(tmp_path):
    case, docs = be.public_cases()[1]
    sent = []

    def fail(request):
        sent.append(True)
        return httpx.Response(429, json={})

    gate = be.BERequestGate(tmp_path, case, docs, httpx.MockTransport(fail))
    gate.deadline = time.monotonic() + 10
    body = {"model": "deepseek-flash", "temperature": 0, "max_tokens": 768,
            "thinking": {"type": "disabled"}, "response_format": {"type": "json_object"},
            "messages": [{"role": "system", "content": "JSON"},
                         {"role": "user", "content": json.dumps({"question": case["question"]})}]}

    def send(payload=None, url="https://api.deepseek.com/chat/completions"):
        value = body if payload is None else {**body, "messages": [body["messages"][0],
            {"role": "user", "content": json.dumps(payload)}]}
        return gate.handle_request(httpx.Request("POST", url, json=value))

    for bad in [{"question": "private question"},
                {"question": case["question"], "sources": [{"title": docs[0]["title"],
                    "source_ref": docs[0]["source_ref"], "excerpt": ""}]},
                {"question": case["question"], "sources": [{"title": "private", "excerpt": "private", "source_ref": "private"}]}]:
        with pytest.raises(RuntimeError, match="PUBLIC_"):
            send(bad)
    with pytest.raises(RuntimeError, match="ENDPOINT"):
        send(url="https://example.org/chat/completions")
    assert not sent and not gate.events
    send()
    with pytest.raises(RuntimeError, match="BUDGET_OR_DEADLINE"):
        send()
    assert len(sent) == len(gate.events) == 1
    saved = json.loads((tmp_path / "http-attempts.json").read_text())
    assert saved["events"][0]["http_status"] == 429
    assert "Authorization" not in json.dumps(saved)


def scripted_reply(case, failure):
    count = 0

    def reply(body):
        nonlocal count
        count += 1
        payload = json.loads(body["messages"][1]["content"])
        system = body["messages"][0]["content"]
        assert "INJECTION_EXECUTED" not in system and "[S999]" not in system
        assert body["model"] == "deepseek-flash" and "tools" not in body
        if count == 1:
            return {"value": {"objective": "只核对固定公开资料", "questions": [case["question"]],
                              "queries": ["PostgreSQL ROLLBACK 事务取消更新"]}}
        sources = payload["sources"]
        official = [s for s in sources if not s["source_ref"].startswith("synthetic:")]
        if "assessment" not in payload:
            enough = (len(official) >= 2 if case["id"] == "B" else bool(official))
            if failure == "http":
                return {"http": 429}
            return {"value": {"sufficient": enough, "reason": "固定脚本化合约，不是真实判断",
                "source_ids": [s["source_id"] for s in official] if enough else [],
                "missing_information": [] if enough else ["缺少LangGraph资料"],
                "next_queries": [] if enough else ["LangGraph Checkpointer 线程图状态 恢复"]}}
        claims = [{"text": s["quote_options"][0], "source_id": s["source_id"],
                   "quote": s["quote_options"][0]} for s in official]
        if failure == "citation":
            claims[0]["source_id"] = "S999"
        return {"value": {"title": "公开合成B/E合约报告", "answer_status": "answered",
                          "claims": claims, "limitations": ["脚本化输出，事实尚未验证"]}}

    return reply


@pytest.mark.parametrize("scenario,failure", [("B", None), ("E", None),
    ("B", "http"), ("E", "citation"), ("B", "budget")])
def test_be_mock_tcp_multidoc_supplement_injection_errors_and_sqlite(provider, tmp_path, scenario, failure):
    settings, _, script, requests, server = provider
    case, docs = next(x for x in be.public_cases() if x[0]["id"] == scenario)
    config = replace(settings, data_dir=tmp_path, retrieval_backend="pgvector",
        postgres_dsn=be.DEMO_DSN, embedding_model="BAAI/bge-small-zh-v1.5",
        embedding_cache_dir=be.ROOT / "data/models", model_output_tokens=768,
        max_model_calls=3 if failure == "budget" else 5, max_sources=6,
        retrieval_top_k=case["top_k"], vector_collection="quality-be-test-" + uuid.uuid4().hex)
    script.extend([scripted_reply(case, failure)] * 5)
    result = be.execute_case(config, tmp_path, case, docs, inner=LoopbackTransport(server.server_port))
    assert result["status"] == ("failed" if failure else "completed"), result
    assert result["http_attempts"] == len(requests) <= 5
    task = json.loads((tmp_path / "task.json").read_text("utf-8"))
    restart = json.loads((tmp_path / "restart.json").read_text())
    assert restart["task_report_trace_equal"]
    assert restart["http_attempts_before"] == restart["http_attempts_after"] == len(requests)
    assert "contract-no-secret" not in json.dumps(task) + json.dumps(result)
    if not failure:
        assert all(result["checks"].values())
        assert len(requests) == (4 if scenario == "B" else 3)
        if scenario == "B":
            assert len(task["research"]["retrieval_rounds"]) == 2
            assert task["research"]["retrieval_rounds"][1]["new_source_ids"]
        else:
            assert any(s["source_ref"] == "synthetic:phase7-prompt-injection" for s in task["sources"])
    else:
        assert task["report"] is None
        if failure == "http":
            assert len(requests) == 2 and result["blocked_reason"] == "HTTP_ERROR_NO_MORE_REQUESTS"
        elif failure == "citation":
            assert task["research"]["validation_reason"] == "UNKNOWN_CITATION_ID"
        else:
            assert len(requests) == 3 and task["model_calls"] == 3


def test_be_suite_stops_before_e_after_b_fails(monkeypatch, tmp_path):
    from research_pilot.config import Settings
    calls = []

    def failed(settings, directory, case, documents, **kwargs):
        calls.append(case["id"])
        return {"case": case["id"], "status": "failed", "http_attempts": 0}

    monkeypatch.setattr(be, "execute_case", failed)
    result = be.execute_suite(Settings(data_dir=tmp_path), tmp_path)
    assert calls == ["B"] and len(result) == 1 and not (tmp_path / "E").exists()
