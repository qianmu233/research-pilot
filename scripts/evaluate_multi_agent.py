"""Reproducible A/B/C comparison on public synthetic enterprise documents."""
from __future__ import annotations

import argparse
import hashlib
import json
import statistics
import time
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path
from tempfile import TemporaryDirectory
from threading import Lock

from research_pilot.config import Settings
from research_pilot.local_llm import LocalStructuredModel, ProviderFailure, verify_local_model
from research_pilot.model import MockResearchModel
from research_pilot.multi_schema import (
    EnterpriseReport,
    ReviewDecision,
    SupervisorPlan,
    WorkerAssessment,
)
from research_pilot.runtime import ResearchRuntime
from research_pilot.schema import CreateTask, IngestText

ROOT = Path(__file__).resolve().parents[1]
DATASET = ROOT / "benchmarks/multi_agent_v1/dataset.json"
QUALITY_CASES = DATASET.with_name("quality_cases.json")
ARMS = ("A_single", "B_fixed", "C_dynamic")
LIMITS = {"max_rounds": 2, "max_model_calls": 8, "retrieval_top_k": 1, "max_sources": 8}


class FixtureResearchModel(MockResearchModel):
    structured_research = True

    def __init__(self, arm: str, case: dict, inject_failure: bool):
        self.arm = arm
        self.case = case
        self.inject_failure = inject_failure

    def fail_once(self):
        if self.inject_failure:
            self.inject_failure = False
            raise ProviderFailure("MODEL_SERVER_ERROR")

    def generate(self, stage: str, payload: dict, timeout: float) -> tuple[dict, dict]:
        question = payload["question"]
        dimensions = self.case["scope"].split("：", 1)[1].split("；", 1)[0].split("、")
        plan, _ = super().generate_multi(
            SupervisorPlan, "", {"question": question, "scope": self.case["scope"], "max_subtasks": 6}, timeout,
        )
        subjects = [s["objective"] for s in plan["subtasks"]]
        if stage == "plan":
            return {"objective": question, "questions": [question], "queries": [question]}, {}
        if stage == "assess":
            self.fail_once()
            sources = payload["sources"]
            missing = [(subject, dimension) for subject in subjects for dimension in dimensions
                       if not any(subject in s["title"] and dimension in s["excerpt"] for s in sources)]
            return {"sufficient": not missing, "reason": "Deterministic fixture rules",
                    "source_ids": [s["source_id"] for s in sources],
                    "missing_information": [" ".join(pair) for pair in missing[:4]],
                    "next_queries": [" ".join(pair) for pair in missing[:1]]}, {}
        report, usage = super().generate_multi(EnterpriseReport, "",
            {**payload, "sufficient": payload["assessment"]["sufficient"]}, timeout)
        for claim in report["claims"]:
            claim.pop("section")
        return report, usage

    def generate_multi(self, schema, instruction, payload, timeout):
        if schema is WorkerAssessment and payload["objective"] == self.case["fixed_subjects"][0]:
            self.fail_once()
        if self.arm == "B_fixed" and schema is SupervisorPlan:
            dimensions = self.case["scope"].split("：", 1)[1].split("；", 1)[0].split("、")
            return {"subtasks": [
                {"objective": subject, "scope": self.case["scope"], "dimensions": dimensions,
                 "constraints": [self.case["scope"]], "queries": [subject]}
                for subject in self.case["fixed_subjects"]
            ]}, {}
        result, usage = super().generate_multi(schema, instruction, payload, timeout)
        if self.arm == "B_fixed" and schema is ReviewDecision:
            result["followups"] = []
        if self.arm == "B_fixed" and schema is WorkerAssessment:
            result["next_queries"] = []
        return result, usage


def score(case: dict, task: dict) -> dict:
    gold = {item["id"]: item for item in case["documents"] if item["dimensions"]}
    retrieved = {source["source_ref"] for source in task["sources"]}
    coverage = {(item["subject"], dimension) for item in gold.values()
                if item["id"] in retrieved for dimension in item["dimensions"]}
    expected = {(item["subject"], dimension) for item in gold.values() for dimension in item["dimensions"]}
    sources = {source["source_id"]: source["excerpt"] for source in task["sources"]}
    claims = task["research"].get("report", {}).get("claims", [])
    valid = sum(c["quote"] in sources.get(c["source_id"], "") for c in claims)
    tokens = [event.get("total_tokens") for event in task["model_events"]]
    return {
        "status": task["status"], "quality": task["research"].get(
            "quality", task["research"].get("report", {}).get("answer_status")
        ),
        "key_evidence": [len(retrieved & gold.keys()), len(gold)],
        "dimensions": [len(coverage), len(expected)],
        "valid_citations": [valid, len(claims)],
        "model_calls": task["model_calls"],
        "total_tokens": sum(tokens) if tokens and all(isinstance(n, int) for n in tokens) else None,
    }


def ingest(runtime, case):
    for doc in case["documents"]:
        runtime.ingest_text(IngestText(title=doc["title"], content=doc["content"], source_ref=doc["id"]))


def run_fixture(case, arm, *, failure=False):
    with TemporaryDirectory(prefix="research-pilot-eval-") as directory:
        settings = Settings(data_dir=Path(directory), **LIMITS)
        model = FixtureResearchModel(arm, case, inject_failure=failure)
        queries = Counter()
        lock = Lock()

        def open_runtime():
            runtime = ResearchRuntime(settings, model=model)
            search = runtime.local.search

            def observed(query, limit):
                with lock:
                    queries[query] += 1
                return search(query, limit)

            runtime.local.search = observed
            return runtime

        runtime = open_runtime()
        ingest(runtime, case)
        task_id = runtime.create_task(CreateTask(question=case["question"], scope=case["scope"],
                                                mode="single" if arm == "A_single" else "multi"))
        started = time.perf_counter()
        try:
            runtime.run_task(task_id)
            before = runtime.get_task(task_id)
        finally:
            runtime.close()
        if failure:
            recorded = dict(queries)
            runtime = open_runtime()
            try:
                runtime.run_task(task_id)
                task = runtime.get_task(task_id)
            finally:
                runtime.close()
            return {
                "status_before": before["status"], "phase_before": before["phase"],
                "model_calls_before": before["model_calls"], "model_calls_after": task["model_calls"],
                "repeated_existing_queries": {q: queries[q] - count for q, count in recorded.items()
                                              if queries[q] > count},
                "query_counts_before": recorded, "query_counts_after": dict(queries),
                "subtask_attempts": {c["objective"]: c["total_attempts"]
                                     for c in task.get("progress", {}).get("subtasks", [])},
                "status_after": task["status"], "quality_after": score(case, task)["quality"],
            }
        return {**score(case, before), "elapsed_ms": round(1000 * (time.perf_counter() - started), 2),
                "retrieval_queries": dict(queries), "trace": before["trace"]}


def aggregate(rows):
    columns = ("key_evidence", "dimensions", "valid_citations")
    result = {}
    for arm in ARMS:
        samples = [row for row in rows if row["arm"] == arm]
        summary = {}
        for column in columns:
            hit, total = [sum(row[column][i] for row in samples) for i in (0, 1)]
            summary[column] = [hit, total]
        summary["elapsed_ms_median"] = round(statistics.median(row["elapsed_ms"] for row in samples), 2)
        summary["model_calls_mean"] = statistics.mean(row["model_calls"] for row in samples)
        summary["completed"] = sum(row["status"] == "completed" for row in samples)
        summary["total_tokens"] = None
        result[arm] = summary
    return result


class LocalComparisonModel(LocalStructuredModel):
    def __init__(self, settings, case, arm):
        super().__init__(settings)
        self.case, self.arm = case, arm
        self.identity = {**verify_local_model(settings), "provider": "ollama",
                         "base_url": settings.model_base_url}
        self.provider_calls = 0
        self.lock = Lock()

    def request(self, schema, provider_schema, messages, timeout):
        with self.lock:
            self.provider_calls += 1
        return super().request(schema, provider_schema, messages, timeout)

    def generate_multi(self, schema, instruction, payload, timeout):
        if self.arm == "B_fixed" and schema is SupervisorPlan:
            fixture = FixtureResearchModel("B_fixed", self.case, inject_failure=False)
            result, _ = fixture.generate_multi(schema, instruction, payload, timeout)
            return result, {"provider": "fixed_fixture"}
        result, usage = super().generate_multi(schema, instruction, payload, timeout)
        if self.arm == "B_fixed":
            if schema is ReviewDecision:
                result["followups"] = []
            elif schema is WorkerAssessment:
                result["next_queries"] = []
        return result, usage


def local_smoke(case, arm="C_dynamic"):
    with TemporaryDirectory(prefix="research-pilot-ollama-") as directory:
        settings = Settings(data_dir=Path(directory), model_backend="ollama",
                            model_name="qwen3:4b-instruct-2507-q4_K_M",
                            model_base_url="http://127.0.0.1:11434/v1",
                            embedding_cache_dir=ROOT / "data/models",
                            model_context_tokens=4096, step_timeout_seconds=90,
                            task_timeout_seconds=300, multi_max_concurrency=2, **LIMITS)
        model = LocalComparisonModel(settings, case, arm)
        runtime = ResearchRuntime(settings, model=model)
        try:
            ingest(runtime, case)
            task_id = runtime.create_task(CreateTask(question=case["question"], scope=case["scope"],
                                                    mode="single" if arm == "A_single" else "multi"))
            started = time.perf_counter()
            runtime.run_task(task_id)
            task = runtime.get_task(task_id)
            initial_status = task["status"]
            if task["phase"] == "waiting_for_retry":
                runtime.run_task(task_id)
                task = runtime.get_task(task_id)
            elapsed = round(1000 * (time.perf_counter() - started), 2)
        finally:
            runtime.close()
        events = task["model_events"]
        accounted = [event["total_tokens"] for event in events
                     if event.get("provider") != "fixed_fixture" and isinstance(event.get("total_tokens"), int)]
        return {"case": case["id"], "arm": arm, "model": runtime.model_identity,
                "elapsed_ms": elapsed, **score(case, task),
                "total_tokens": sum(accounted) if len(accounted) == model.provider_calls else None,
                "provider_calls": model.provider_calls, "token_events": len(accounted),
                "initial_status": initial_status, "phase": task["phase"], "error_code": task["error_code"],
                "trace": task["trace"], "model_events": task["model_events"],
                "research": task["research"], "markdown": task["report"],
                "sources": [{k: s[k] for k in ("source_id", "source_ref", "title", "excerpt")}
                            for s in task["sources"]],
                "subtasks": [{k: c.get(k) for k in (
                    "objective", "status", "initial_queries", "dimensions", "covered_dimensions",
                    "rounds", "supplement", "started_at", "completed_at", "model_calls", "error_code",
                )} for c in task.get("progress", {}).get("subtasks", [])]}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--repeats", type=int, default=3)
    parser.add_argument("--output", type=Path, required=True)
    local = parser.add_mutually_exclusive_group()
    local.add_argument("--local-ollama", choices=("rag", "logs"),
                       help="Run one separate real-model smoke against the pinned loopback Ollama.")
    local.add_argument("--local-quality-suite", action="store_true",
                       help="Compare A/B/C on RAG and run two more real multi-mode cases.")
    args = parser.parse_args()
    if args.repeats < 1:
        parser.error("--repeats must be positive")
    if args.output.exists():
        parser.error("--output already exists; choose a new path to preserve the previous run")
    raw = DATASET.read_bytes()
    cases = json.loads(raw)["cases"]
    result = {"created_at": datetime.now(UTC).isoformat(), "dataset_sha256": hashlib.sha256(raw).hexdigest(),
              "limits": LIMITS}
    if args.local_ollama:
        result["local_ollama"] = local_smoke(next(case for case in cases if case["id"] == args.local_ollama))
    elif args.local_quality_suite:
        quality_bytes = QUALITY_CASES.read_bytes()
        rag = next(case for case in cases if case["id"] == "rag")
        result["quality_cases_sha256"] = hashlib.sha256(quality_bytes).hexdigest()
        result["real_rows"] = [local_smoke(rag, arm) for arm in ARMS]
        result["real_rows"].extend(local_smoke(case) for case in json.loads(quality_bytes)["cases"])
    else:
        rows = [{"case": case["id"], "arm": arm, "repeat": repeat, **run_fixture(case, arm)}
                for repeat in range(1, args.repeats + 1) for case in cases for arm in ARMS]
        result.update(rows=rows, summary=aggregate(rows),
                      recovery={arm: run_fixture(cases[0], arm, failure=True) for arm in ARMS})
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open("x", encoding="utf-8", newline="\n") as stream:
        json.dump(result, stream, indent=2, ensure_ascii=False)
        stream.write("\n")
    if "real_rows" in result:
        for row in result["real_rows"]:
            print(row["case"], row["arm"], row["status"], row["quality"], row["valid_citations"])
    else:
        print(json.dumps(result.get("summary", result.get("local_ollama")), indent=2, ensure_ascii=False))


if __name__ == "__main__":
    main()
