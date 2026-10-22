"""Phase 7.3 public synthetic A; dry-run unless separately authorized.

Real loopback TCP FastAPI, existing graph, cached Chinese BGE and demo PgVector.
No subprocess model service, dotenv, retries, resume, private corpus or A/B/E loop.
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import socket
import subprocess
import threading
import time
from contextlib import contextmanager
from dataclasses import replace
from datetime import datetime, timedelta, timezone
from decimal import Decimal

import httpx

from scripts.deepseek_preview import PUBLIC_DOCUMENT, PUBLIC_QUESTION, ROOT, write_once

BASELINE = "0304f7783700636f14b494a30745388069f20f3b"
PRICE_DATE = "2026-10-21"
DEMO_DSN = ("postgresql://researchpilot_demo:researchpilot_local_demo@"
            "127.0.0.1:15432/researchpilot_demo")


def plan():
    return {"mode": "dry_run_no_settings_no_network", "scenario": "public-synthetic-A-only",
            "max_http_attempts": 5, "max_rounds": 3, "deadline_seconds": 300,
            "context_allowance": 8192, "output_per_request": 768,
            "price_date": PRICE_DATE, "input_usd_per_million": 0.30,
            "output_usd_per_million": 1.20, "estimated_max_usd": 0.016896,
            "approval_budget_usd": 0.02,
            "limits": "Byte/framing bound, not official tokenizer or wallet hard cap"}


def disable_tracing():
    for name in ("LANGSMITH_TRACING", "LANGSMITH_TRACING_V2", "LANGCHAIN_TRACING",
                 "LANGCHAIN_TRACING_V2", "LANGSMITH_OTEL_ENABLED", "DD_TRACE_ENABLED"):
        os.environ[name] = "false"
    os.environ.update(OTEL_SDK_DISABLED="true", OTEL_TRACES_EXPORTER="none",
                      OTEL_METRICS_EXPORTER="none", OTEL_LOGS_EXPORTER="none",
                      OPENAI_LOG="off", WANDB_DISABLED="true", HF_HUB_OFFLINE="1",
                      TRANSFORMERS_OFFLINE="1", HF_HUB_DISABLE_TELEMETRY="1",
                      DO_NOT_TRACK="1")
    logging.disable(logging.CRITICAL)
    from langchain_core.globals import set_debug, set_verbose
    set_debug(False)
    set_verbose(False)


class RequestGate(httpx.BaseTransport):
    """Persist attempts BEFORE I/O. Fail closed; headers/bodies never logged."""
    def __init__(self, directory, inner=None):
        self.directory = directory
        self.inner = inner if inner is not None else httpx.HTTPTransport(retries=0, trust_env=False)
        self.events = []
        self.lock = threading.Lock()
        self.blocked_reason = None
        self.deadline = None
        self.enabled = True

    def save(self):
        # This experiment owns the new directory; update its ledger, never old evidence.
        path = self.directory / "http-attempts.json"
        path.write_text(json.dumps({"http_attempts": len(self.events), "events": self.events,
                                  "blocked_reason": self.blocked_reason}, indent=2), "utf-8")

    def validate_public_payload(self, payload):
        if payload.get("question") != PUBLIC_QUESTION:
            raise RuntimeError("EXPERIMENT_PUBLIC_QUESTION_STOP")
        if any(s.get("source_ref") != PUBLIC_DOCUMENT.source_ref or
               s.get("excerpt") not in PUBLIC_DOCUMENT.content
               for s in payload.get("sources", [])):
            raise RuntimeError("EXPERIMENT_PUBLIC_SOURCE_STOP")

    def handle_request(self, request):
        with self.lock:
            if (not self.enabled or self.blocked_reason or len(self.events) >= 5 or
                    self.deadline is None or time.monotonic() >= self.deadline):
                raise RuntimeError("EXPERIMENT_HTTP_BUDGET_OR_DEADLINE_STOP")
            url = request.url
            if (request.method != "POST" or url.scheme != "https" or
                    url.host != "api.deepseek.com" or url.port not in {None, 443} or
                    url.path != "/chat/completions" or url.query):
                raise RuntimeError("EXPERIMENT_ENDPOINT_STOP")
            body = json.loads(request.content)
            if (body.get("model") != "deepseek-flash" or body.get("max_tokens") != 768 or
                    body.get("response_format") != {"type": "json_object"} or
                    body.get("thinking") != {"type": "disabled"} or
                    body.get("temperature") != 0 or body.get("stream", False) or
                    any(k in body for k in ("tools", "functions", "max_completion_tokens"))):
                raise RuntimeError("EXPERIMENT_PARAMETERS_STOP")
            messages = body.get("messages", [])
            if ([m.get("role") for m in messages] != ["system", "user"] or
                    any(not isinstance(m.get("content"), str) for m in messages)):
                raise RuntimeError("EXPERIMENT_MESSAGES_STOP")
            payload = json.loads(messages[1]["content"])
            self.validate_public_payload(payload)
            if sum(len(m["content"].encode("utf-8")) for m in messages) + 256 + 768 > 8192:
                raise RuntimeError("EXPERIMENT_INPUT_BUDGET_STOP")
            item = {"attempt": len(self.events) + 1, "status": "attempt_reserved",
                    "http_status": None, "usage": None}
            self.events.append(item)
            self.save()  # Failure here prevents any network request.
            remaining = self.deadline - time.monotonic()
            request.extensions["timeout"] = {k: min(float(v), remaining) if v else remaining
                                             for k, v in request.extensions.get("timeout", {}).items()}
            started = time.monotonic()
            try:
                response = self.inner.handle_request(request)
                response.read()
                item.update(status="response_received", http_status=response.status_code)
                if response.status_code != 200:
                    self.blocked_reason = "HTTP_ERROR_NO_MORE_REQUESTS"
                else:
                    data = response.json()
                    usage = data.get("usage", {})
                    keys = ("prompt_tokens", "completion_tokens", "total_tokens")
                    if all(type(usage.get(k)) is int and usage[k] >= 0 for k in keys):
                        item["usage"] = {k: usage[k] for k in keys}
                        if (usage["prompt_tokens"] > 8192 or usage["completion_tokens"] > 768 or
                                usage["total_tokens"] != usage["prompt_tokens"] + usage["completion_tokens"]):
                            self.blocked_reason = "PROVIDER_USAGE_EXCEEDS_BUDGET"
                    else:
                        self.blocked_reason = "PROVIDER_USAGE_UNKNOWN"
                return response
            except Exception:
                item["status"] = "transport_or_response_failure"
                self.blocked_reason = "TRANSPORT_OR_RESPONSE_FAILURE_NO_MORE_REQUESTS"
                raise
            finally:
                item["elapsed_seconds"] = round(time.monotonic() - started, 3)
                self.save()

    def close(self):
        self.inner.close()


@contextmanager
def serve(runtime):
    """Real TCP, same-process Uvicorn thread so the request gate remains in scope."""
    import uvicorn

    from research_pilot.api import create_app
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    server = uvicorn.Server(uvicorn.Config(create_app(runtime), log_config=None, access_log=False,
                                         timeout_graceful_shutdown=5))
    thread = threading.Thread(target=server.run, kwargs={"sockets": [listener]}, daemon=True)
    thread.start()
    try:
        deadline = time.monotonic() + 15
        while not server.started:
            if not thread.is_alive() or time.monotonic() >= deadline:
                raise RuntimeError("LOCAL_HTTP_START_FAILED")
            time.sleep(.05)
        with httpx.Client(base_url=f"http://127.0.0.1:{listener.getsockname()[1]}",
                          trust_env=False, follow_redirects=False, timeout=10) as client:
            yield client
    finally:
        server.should_exit = True
        thread.join(15)
        listener.close()
        if thread.is_alive():
            raise RuntimeError("LOCAL_HTTP_SHUTDOWN_FAILED")


def get_json(client, path, expected=200):
    response = client.get(path)
    if response.status_code != expected:
        raise RuntimeError("LOCAL_HTTP_QUERY_FAILED")
    return response.json()


def execute(settings, directory, *, inner=None):
    from research_pilot.deepseek import DeepSeekStructuredModel
    from research_pilot.runtime import ResearchRuntime
    gate = RequestGate(directory, inner)
    gate.save()
    summary = {"status": "failed", "error_code": "LOCAL_PREFLIGHT_OR_EXPERIMENT_FAILURE",
               "provider": "deepseek", "requested_model": "deepseek-flash",
               "fact_review": "pending_manual_review", "facts_verified": False}
    phase = "embedding_pgvector_initialization"
    with httpx.Client(transport=gate, trust_env=False, follow_redirects=False) as model_client:
        try:
            model = DeepSeekStructuredModel(settings, http_client=model_client)
            runtime = ResearchRuntime(settings, model=model)
            try:
                phase = "local_http_start"
                with serve(runtime) as client:
                    health = get_json(client, "/health")
                    if health["model_backend"] != "deepseek" or health["retrieval_backend"] != "pgvector":
                        raise RuntimeError("LOCAL_HTTP_PROFILE_MISMATCH")
                    imported = client.post("/api/documents/text", json=PUBLIC_DOCUMENT.model_dump())
                    if imported.status_code != 201:
                        raise RuntimeError("PUBLIC_DOCUMENT_IMPORT_FAILED")
                    write_once(directory / "import.json", imported.json())
                    # A real BGE/PgVector preflight before the first paid request.
                    hits = runtime.local.search(PUBLIC_QUESTION, 1)
                    if not hits or hits[0]["source_ref"] != PUBLIC_DOCUMENT.source_ref:
                        raise RuntimeError("PUBLIC_EVIDENCE_PREFLIGHT_FAILED")
                    write_once(directory / "retrieval-preflight.json", hits)
                    phase = "task_submission_or_execution"
                    gate.deadline = time.monotonic() + 300
                    created = client.post("/api/tasks", json={"question": PUBLIC_QUESTION,
                                          "scope": "仅据公开合成演示笔记回答"})
                    if created.status_code != 202:
                        raise RuntimeError("TASK_SUBMISSION_FAILED_DO_NOT_RESUBMIT")
                    tid = created.json()["task_id"]
                    while True:
                        task = get_json(client, f"/api/tasks/{tid}")
                        if task["status"] in {"completed", "failed", "timed_out", "interrupted"}:
                            break
                        if time.monotonic() > gate.deadline + 15:
                            raise RuntimeError("EXPERIMENT_WAIT_DEADLINE")
                        time.sleep(.1)
                    trace = get_json(client, f"/api/tasks/{tid}/trace")
                    report = get_json(client, f"/api/tasks/{tid}/report",
                                      200 if task["status"] == "completed" else 409)
                    write_once(directory / "A.json", task)
                    write_once(directory / "trace.json", trace)
                    write_once(directory / "report-api.json", report)
            finally:
                runtime.close()
            # Reopen both SQLite stores and the HTTP server; GET only, no /resume.
            gate.enabled = False
            phase = "sqlite_http_restart_query"
            attempts = len(gate.events)
            restored = ResearchRuntime(settings, model=model)
            try:
                with serve(restored) as client:
                    same = (get_json(client, f"/api/tasks/{tid}") == task and
                            get_json(client, f"/api/tasks/{tid}/trace") == trace and
                            get_json(client, f"/api/tasks/{tid}/report",
                                     200 if task["status"] == "completed" else 409) == report)
                    write_once(directory / "restart.json", {"same_task_report_trace": same,
                               "http_attempts_before": attempts, "http_attempts_after": len(gate.events),
                               "kind": "runtime_and_http_restart_same_process_not_process_crash"})
            finally:
                restored.close()
            research = task["research"]
            checks = {"answered": research.get("report", {}).get("answer_status") == "answered",
                      "citation_valid": research.get("citation_valid") is True,
                      "evidence_unverified": task["evidence_status"] == "unverified",
                      "sources_public": bool(task["sources"]) and all(
                          s["source_ref"] == PUBLIC_DOCUMENT.source_ref and
                          s["document_id"] == imported.json()["document_id"] and
                          s["locator"].startswith("pgvector:") for s in task["sources"]),
                      "rounds_bounded": 1 <= len(research.get("retrieval_rounds", [])) <= 3,
                      "accounting_matches": task["model_calls"] == attempts <= 5,
                      "restart_equal_no_requests": same and attempts == len(gate.events),
                      "no_tool_errors": not task["tool_errors"],
                      "all_http_ok": all(e["http_status"] == 200 for e in gate.events)}
            success = task["status"] == "completed" and all(checks.values()) and not gate.blocked_reason
            summary.update(status="completed" if success else "failed", checks=checks,
                           task_id=tid, task_status=task["status"],
                           error_code=None if success else (task["error_code"] or
                               gate.blocked_reason or "A_ACCEPTANCE_FAILED"))
        except Exception as exc:  # noqa: BLE001 -- no raw error, bodies or credential logging
            summary["error_type"] = type(exc).__name__
            summary["error_code"] = "EXPERIMENT_" + phase.upper() + "_FAILED"
            summary["failure_stage"] = phase
        finally:
            known = all(e["usage"] is not None for e in gate.events)
            inp = sum(e["usage"]["prompt_tokens"] for e in gate.events if e["usage"])
            out = sum(e["usage"]["completion_tokens"] for e in gate.events if e["usage"])
            summary.update(http_attempts=len(gate.events), usage_complete=known,
                           observed_input_tokens=inp, observed_output_tokens=out,
                           estimated_cost_usd=float((Decimal(inp)*Decimal(".3") +
                               Decimal(out)*Decimal("1.2"))/Decimal(1000000)) if known else None,
                           price_date=PRICE_DATE, blocked_reason=gate.blocked_reason)
            write_once(directory / "summary.json", summary)
    return summary


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--execute-paid", action="store_true")
    parser.add_argument("--smoke-result")
    args = parser.parse_args()
    if not args.execute_paid:
        print(json.dumps(plan(), indent=2))
        return 0
    disable_tracing()
    from pathlib import Path

    from research_pilot.config import Settings
    try:
        if datetime.now(timezone(timedelta(hours=8))).date().isoformat() != PRICE_DATE:
            raise ValueError("PRICE_SNAPSHOT_EXPIRED")
        for name in ("RESEARCH_MODEL_BACKEND", "RESEARCH_OPENAI_BASE_URL",
                     "RESEARCH_OPENAI_MODEL", "RESEARCH_OPENAI_API_KEY"):
            if not os.environ.get(name, "").strip():
                raise ValueError("REQUIRED_ENVIRONMENT_MISSING")
        if (os.environ["RESEARCH_MODEL_BACKEND"] not in {"deepseek", "openai"} or
                os.environ["RESEARCH_OPENAI_MODEL"] != "deepseek-flash" or
                os.environ["RESEARCH_OPENAI_BASE_URL"].rstrip("/") != "https://api.deepseek.com"):
            raise ValueError("MODEL_PROFILE_MISMATCH")
        for command, expected in [(["git", "branch", "--show-current"], "feat/deepseek-provider"),
                                  (["git", "rev-parse", "main"], BASELINE)]:
            if subprocess.check_output(command, cwd=ROOT, text=True, stderr=subprocess.DEVNULL).strip() != expected:
                raise ValueError("GIT_BASELINE_OR_BRANCH_MISMATCH")
        source = Path(args.smoke_result).resolve()
        if not source.is_relative_to(ROOT / "data") or source.name != "smoke.json":
            raise ValueError("SMOKE_PATH_INVALID")
        smoke = json.loads(source.read_text("utf-8"))
        check = json.loads(source.with_name("smoke-check.json").read_text("utf-8"))
        if (smoke.get("status") != "completed" or smoke.get("provider") != "deepseek" or
                smoke.get("model") != "deepseek-flash" or smoke.get("model_calls") != 1 or
                check != {"http_attempts": 1, "error_code": None, "exit_code": 0}):
            raise ValueError("SUCCESSFUL_SMOKE_REQUIRED")
        # Select the structured provider explicitly; never legacy openai/Mock.
        os.environ.update(RESEARCH_MODEL_BACKEND="deepseek", RESEARCH_SEARCH_BACKEND="none",
                          RESEARCH_RETRIEVAL_BACKEND="lexical")
        settings = Settings.from_env()
        directory = source.parent / "A-http"
        settings = replace(settings, data_dir=directory, model_context_tokens=8192,
            model_output_tokens=768, max_model_calls=5, max_rounds=3, task_timeout_seconds=300,
            step_timeout_seconds=60, retrieval_backend="pgvector", postgres_dsn=DEMO_DSN,
            vector_collection="phase73-" + source.parent.name.removeprefix("phase72-paid-"),
            embedding_model="BAAI/bge-small-zh-v1.5", embedding_query_instruction=False,
            embedding_cache_dir=ROOT / "data/models", retrieval_top_k=1, vector_min_score=.5)
        settings.validate()
        if Decimal(str(plan()["estimated_max_usd"])) > Decimal(".02"):
            raise ValueError("COST_ESTIMATE_EXCEEDS_APPROVAL")
        directory.mkdir(exist_ok=False)  # Refuse manual retry/rerun of this experiment.
        write_once(directory / "budget.json", plan())
    except Exception:  # noqa: BLE001 -- never echo configuration, exceptions or keys
        print("Preflight stopped; no paid request. Check configuration/date/Git/smoke/existing A-http.")
        return 1
    summary = execute(settings, directory)
    print("Saved local evidence:", directory.relative_to(ROOT), "status:", summary["status"],
          "HTTP attempts:", summary["http_attempts"], "error:", summary["error_code"])
    return 0 if summary["status"] == "completed" else 1


if __name__ == "__main__":
    raise SystemExit(main())
