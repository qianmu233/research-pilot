"""Local regression of paid-run limits. No real credential or remote transport."""
import json
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime
from zoneinfo import ZoneInfo

import httpx
import pytest

from scripts import deepseek_be as be


def request_for(case, system="JSON"):
    return httpx.Request("POST", "https://api.deepseek.com/chat/completions", json={
        "model":"deepseek-flash", "temperature":0, "max_tokens":768,
        "thinking":{"type":"disabled"}, "response_format":{"type":"json_object"},
        "messages":[{"role":"system", "content":system},
                    {"role":"user", "content":json.dumps({"question":case["question"]})}]})


def test_gate_7168_utf8_byte_boundary_is_enforced_before_network(tmp_path):
    case, docs = be.public_cases()[0]
    sent = []

    def reply(request):
        ledger = json.loads((tmp_path / "http-attempts.json").read_text())
        assert ledger["events"][-1]["status"] == "attempt_reserved"
        sent.append(True)
        return httpx.Response(200, json={"usage":{"prompt_tokens":100, "completion_tokens":10, "total_tokens":110}})

    gate = be.BERequestGate(tmp_path, case, docs, httpx.MockTransport(reply))
    gate.deadline = time.monotonic()+10
    n = 7168-len(json.dumps({"question":case["question"]}).encode("utf-8"))
    with pytest.raises(RuntimeError, match="INPUT_BUDGET"):
        gate.handle_request(request_for(case, "x"*(n+1)))
    assert not sent and not gate.events
    gate.handle_request(request_for(case, "x"*n))
    assert len(sent) == len(gate.events) == 1


def test_concurrent_shared_gate_has_five_attempts_and_two_cases_have_ten(tmp_path):
    total_sent = []
    for case, docs in be.public_cases():
        directory = tmp_path/case["id"]
        directory.mkdir()

        def reply(request):
            total_sent.append(True)
            return httpx.Response(200,json={"usage":{"prompt_tokens":100, "completion_tokens":10,"total_tokens":110}})

        gate = be.BERequestGate(directory, case, docs, httpx.MockTransport(reply))
        gate.deadline = time.monotonic()+10

        def attempt(_, gate=gate, case=case):
            try:
                gate.handle_request(request_for(case))
                return True
            except RuntimeError:
                return False

        with ThreadPoolExecutor(max_workers=8) as pool:
            assert sum(pool.map(attempt,range(12))) == 5
        assert len(gate.events) == 5
        gate.enabled = False
        with pytest.raises(RuntimeError,match="BUDGET_OR_DEADLINE"):
            gate.handle_request(request_for(case))
    assert len(total_sent) == 10


def test_ledger_write_failure_prevents_any_http_attempt(tmp_path, monkeypatch):
    case, docs = be.public_cases()[0]
    sent = []
    gate = be.BERequestGate(tmp_path,case,docs,httpx.MockTransport(lambda r: sent.append(True)))
    gate.deadline = time.monotonic()+10

    def unwritable():
        raise OSError("synthetic ledger failure")

    monkeypatch.setattr(gate,"save",unwritable)
    with pytest.raises(OSError):
        gate.handle_request(request_for(case))
    assert not sent


def test_windows_paid_date_path_has_working_timezone_data():
    # The existing paid main() uses this timezone; check it without entering paid mode.
    assert datetime.now(ZoneInfo("Asia/Shanghai")).date().isoformat() == be.DATE
