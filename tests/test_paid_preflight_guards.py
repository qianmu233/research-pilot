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
    # Check installed timezone data with a fixed instant, not today's date.
    instant = datetime.fromisoformat("2026-10-22T15:59:00+00:00")
    assert instant.astimezone(ZoneInfo("Asia/Shanghai")).isoformat() == "2026-10-22T23:59:00+08:00"


@pytest.mark.parametrize("utc_instant,allowed", [
    ("2026-10-21T15:59:59+00:00", False),  # Shanghai: previous day
    ("2026-10-21T16:00:00+00:00", True),   # Shanghai: reviewed day starts
    ("2026-10-22T15:59:59+00:00", True),   # Shanghai: reviewed day ends
    ("2026-10-22T16:00:00+00:00", False),  # Shanghai: 2026-10-23
    ("2026-10-23T16:00:00+00:00", False),  # Shanghai: 2026-10-24
    ("2027-01-01T00:00:00+00:00", False),  # A later year stays expired
])
def test_paid_date_gate_with_fixed_clock_stops_before_credentials_or_http(
    monkeypatch, tmp_path, capsys, utc_instant, allowed,
):
    """Exercise the real CLI gate, then deliberately stop at public-fixture review.

    Passing the date gate is observed by reaching the next check, never by
    constructing settings, accessing a key or executing the paid suite.
    """
    instant = datetime.fromisoformat(utc_instant)
    clock_calls, reached, forbidden_calls = [], [], []

    class FixedClock:
        @staticmethod
        def now(tz):
            clock_calls.append(tz.key)
            return instant.astimezone(tz)

    def stop_at_fixture_review():
        reached.append("fixture_review")
        raise RuntimeError("TEST_STOP_BEFORE_CREDENTIALS_FILES_OR_MODEL")

    def forbidden(*args, **kwargs):
        forbidden_calls.append(True)
        raise AssertionError("DATE_TEST_MUST_NOT_READ_KEYS_WRITE_EVIDENCE_OR_CALL_MODEL")

    original_get = be.os.environ.get

    def no_credentials(name, *args):
        if name == "RESEARCH_OPENAI_API_KEY":
            return forbidden()
        return original_get(name, *args)

    assert be.DATE == "2026-10-22"  # Do not extend the real paid authorization.
    monkeypatch.setattr(be, "datetime", FixedClock)
    monkeypatch.setattr(be, "disable_tracing", lambda: None)
    monkeypatch.setattr(be, "public_cases", stop_at_fixture_review)
    monkeypatch.setattr(be, "ROOT", tmp_path)
    monkeypatch.setattr(be, "write_once", forbidden)
    monkeypatch.setattr(be, "execute_suite", forbidden)
    monkeypatch.setattr(be.os.environ, "get", no_credentials)
    monkeypatch.setattr(httpx.Client, "send", forbidden)
    monkeypatch.setattr("sys.argv", ["deepseek_be", "--execute-paid", "--acknowledge-public-data",
        "--price-date", "2026-10-22", "--budget-usd", "0.04", "--run-id", "fixedclocktest"])

    # Both paths fail closed: allowed dates hit our intentional next-gate stop;
    # expired dates must stop earlier, without reaching the public data check.
    assert be.main() == 1
    assert clock_calls == ["Asia/Shanghai"]
    assert reached == (["fixture_review"] if allowed else [])
    assert not forbidden_calls and not list(tmp_path.iterdir())
    assert "Preflight stopped; no paid request." in capsys.readouterr().out
