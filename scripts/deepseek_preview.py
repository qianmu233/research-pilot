"""Dry-run by default. Paid smoke/A require a separate, explicit user approval.

No B/E execution, automatic retries, dotenv loading, private corpus or key printing.
"""
import argparse
import json
import time
import uuid
from dataclasses import replace
from pathlib import Path

from research_pilot.config import Settings
from research_pilot.schema import CreateTask, IngestText

ROOT = Path(__file__).resolve().parents[1]
PUBLIC_QUESTION = "公开合成笔记中，演示组件通过什么保存单个线程的图状态？"
PUBLIC_DOCUMENT = IngestText(title="公开合成演示笔记（不是企业资料）",
    content="这是公开合成演示材料，不代表企业或生产系统。演示组件通过检查点保存单个线程的图状态。"
            "使用相同的线程标识可以读取该线程此前保存的状态。本材料没有生产性能或商业数据。",
    source_ref="synthetic:phase72-public-A")


def experiment_plan():
    # USD/1M tokens: 2026-10-21 official PEAK, uncached prices, no cache discount.
    per_call = (8192 * .3 + 768 * 1.2) / 1_000_000
    smoke = (4096 * .3 + 128 * 1.2) / 1_000_000
    return {"execution": "dry_run_no_key_read_no_requests", "model": "deepseek-flash",
        "price_snapshot_date": "2026-10-21", "currency": "USD",
        "smoke": {"max_requests": 1, "input_allowance": 4096, "max_output": 128,
                  "estimated_ceiling_usd": round(smoke, 8)},
        "A": {"max_requests": 5, "input_allowance_per_call": 8192, "max_output_per_call": 768,
              "estimated_ceiling_usd": round(5 * per_call, 8)},
        "smoke_plus_A": {"max_requests": 6, "estimated_ceiling_usd": round(smoke + 5 * per_call, 8),
                         "proposed_approval_budget_usd": .03},
        "future_A_B_E_not_authorized": {"max_requests_excluding_smoke": 15,
            "estimated_ceiling_including_smoke_usd": round(smoke + 15 * per_call, 8),
            "proposed_separate_budget_usd": .06},
        "limits": "Input is an application byte/framing bound, not a measured provider tokenizer. "
                  "Prices and provider enforcement must be rechecked; these estimates are not a wallet hard cap."}


def write_once(path, value):
    with path.open("x", encoding="utf-8") as file:
        json.dump(value, file, ensure_ascii=False, indent=2)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--mode", choices=["smoke", "A"], default="smoke")
    parser.add_argument("--execute-paid", action="store_true",
                        help="Only after explicit user approval of fees and public data transmission")
    parser.add_argument("--smoke-result", type=Path)
    args = parser.parse_args()
    if not args.execute_paid:
        print(json.dumps(experiment_plan(), ensure_ascii=False, indent=2))
        return
    # File/identity checks precede reading the user's runtime credential.
    if args.mode == "A":
        if args.smoke_result is None:
            parser.error("A requires a previously successful --smoke-result")
        source = args.smoke_result.resolve()
        if not source.is_relative_to(ROOT / "data") or source.name != "smoke.json":
            parser.error("Smoke result must be this project's data/.../smoke.json")
        smoke = json.loads(source.read_text("utf-8"))
        if (smoke.get("status") != "completed" or smoke.get("provider") != "deepseek" or
                smoke.get("model") != "deepseek-flash" or smoke.get("model_calls") != 1):
            parser.error("Smoke did not pass; do not issue additional paid requests")
        directory = source.parent / "A"
    else:
        directory = ROOT / "data" / ("phase72-paid-" + uuid.uuid4().hex[:12])
    directory.mkdir(parents=True, exist_ok=False)  # No rerun/resume/overwrite loop.
    # No .env access, no key printing, no ambient tracing. Explicit backend required.
    settings = Settings.from_env()
    if settings.model_backend != "deepseek" or settings.search_backend != "none":
        parser.error("Explicit deepseek backend and search=none required")
    write_once(directory / "budget.json", experiment_plan())
    if args.mode == "smoke":
        from research_pilot.deepseek import DeepSeekStructuredModel
        from research_pilot.store import LocalStore
        settings = replace(settings, model_context_tokens=4096, model_output_tokens=128)
        with_store = LocalStore(directory / "smoke.sqlite3")
        try:
            tid = with_store.create_task(CreateTask(question=PUBLIC_QUESTION))
            number, remaining = with_store.reserve_model_call(tid, "plan", 1, 30)
            started, usage, status = time.monotonic(), {}, "failed"
            try:
                model = DeepSeekStructuredModel(settings)
                plan, usage = model.generate("plan", {"question": PUBLIC_QUESTION, "scope": "公开合成资料"}, remaining)
                if time.monotonic() - started >= remaining:
                    raise TimeoutError("SMOKE_DEADLINE_EXCEEDED")
                status = "completed"
            except Exception as exc:  # noqa: BLE001 -- persist only safe classifications
                usage = getattr(exc, "usage", {})
                write_once(directory / "smoke.json", {"status": "failed", "provider": "deepseek",
                    "model": settings.model_name, "model_calls": 1, "error_type": type(exc).__name__,
                    "usage": usage})
                raise SystemExit("Smoke failed; no retry or A execution") from None
            finally:
                with_store.finish_model_call(tid, number, status, time.monotonic() - started, usage)
            write_once(directory / "smoke.json", {"status": status, "provider": "deepseek",
                "model": settings.model_name, "model_calls": 1, "plan": plan, "usage": usage,
                "elapsed_seconds": round(time.monotonic() - started, 3)})
        finally:
            with_store.close()
    else:
        from research_pilot.runtime import ResearchRuntime
        # Dedicated project demo DB/collection; never reuse an ambient private corpus.
        settings = replace(settings, data_dir=directory, model_context_tokens=8192, model_output_tokens=768,
            max_rounds=3, max_model_calls=5, task_timeout_seconds=300, step_timeout_seconds=60,
            retrieval_backend="pgvector", embedding_model="BAAI/bge-small-zh-v1.5",
            embedding_query_instruction=False, embedding_cache_dir=ROOT / "data/models",
            postgres_dsn="postgresql://researchpilot_demo:researchpilot_local_demo@127.0.0.1:15432/researchpilot_demo",
            vector_collection="phase72-paid-" + uuid.uuid4().hex[:12], retrieval_top_k=1)
        runtime = ResearchRuntime(settings)
        try:
            runtime.ingest_text(PUBLIC_DOCUMENT)
            tid = runtime.create_task(CreateTask(question=PUBLIC_QUESTION, scope="仅据公开合成演示笔记回答"))
            runtime.run_task(tid)
            task = runtime.get_task(tid)
            write_once(directory / "A.json", task)
            if (task["status"] != "completed" or
                    task["research"].get("report", {}).get("answer_status") != "answered"):
                raise SystemExit("A failed; result preserved, no retry or B/E execution")
        finally:
            runtime.close()
    print("Saved local result:", directory.relative_to(ROOT))


if __name__ == "__main__":
    main()
