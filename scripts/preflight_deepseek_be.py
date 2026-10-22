"""Local-only readiness check. No credential values, cloud requests or downloads."""
import argparse
import json
import os
import subprocess
from datetime import datetime, timedelta, timezone

import httpx

from scripts import deepseek_be as be


def check(*, require_clean=False):
    from research_pilot.config import Settings
    from research_pilot.deepseek import DeepSeekStructuredModel
    from research_pilot.vector import ZH_MODEL_NAME, pinned_model_path

    checks = {}
    errors = []
    be.disable_tracing()
    cases = be.public_cases()
    checks["public_fixture_identity"] = [c["id"] for c, _ in cases] == ["B", "E"]
    checks["price_date_current"] = datetime.now(timezone(timedelta(hours=8))).date().isoformat() == be.DATE
    # Presence only. This value is never loaded; the paid wrapper prompts for a fresh key.
    checks["ambient_key_variable_exists"] = "RESEARCH_OPENAI_API_KEY" in os.environ
    try:
        clean = not subprocess.check_output(["git", "status", "--porcelain"], cwd=be.ROOT,
                                            stderr=subprocess.DEVNULL).strip()
        checks["git_clean"] = clean
        unchanged = subprocess.run(["git", "diff", "--quiet", "f3b5c496020e680dabdffceb04622791e20af136",
                                    "--", "research_pilot", "benchmarks"], check=False, cwd=be.ROOT,
                                    stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL).returncode == 0
        checks["business_and_gold_unchanged"] = unchanged
    except Exception:  # noqa: BLE001 -- no raw errors/configuration
        errors.append("GIT_PREFLIGHT_FAILED")

    def forbidden(request):
        raise AssertionError("PREFLIGHT_MUST_NOT_SEND_MODEL_REQUESTS")

    with httpx.Client(transport=httpx.MockTransport(forbidden), trust_env=False) as client:
        settings = Settings(model_backend="deepseek", model_name="deepseek-flash",
            model_base_url="https://api.deepseek.com", model_api_key="preflight-no-secret",
            model_context_tokens=8192, model_output_tokens=768, max_rounds=3,
            task_timeout_seconds=300, step_timeout_seconds=60, max_model_calls=5)
        model = DeepSeekStructuredModel(settings, http_client=client)
        checks["sdk_implicit_retries_disabled"] = model.client.max_retries == 0 and model.client.root_client.max_retries == 0
    try:
        pinned_model_path(be.ROOT / "data/models", local_files_only=True, model_name=ZH_MODEL_NAME)
        checks["six_cached_bge_artifact_hashes"] = True
    except Exception:  # noqa: BLE001
        checks["six_cached_bge_artifact_hashes"] = False
        errors.append("LOCAL_BGE_CACHE_NOT_READY")
    try:
        import psycopg
        # Fixed loopback demo DSN only. Read-only SQL, never DDL or data cleanup.
        with psycopg.connect(be.DEMO_DSN, connect_timeout=3,
                             options="-c default_transaction_read_only=on") as conn, conn.cursor() as cursor:
            cursor.execute("SELECT 1, EXISTS (SELECT 1 FROM pg_extension WHERE extname='vector')")
            row = cursor.fetchone()
            checks["local_pgvector_ready"] = row == (1, True)
    except Exception:  # noqa: BLE001 -- no DSN/driver exception logging
        checks["local_pgvector_ready"] = False
        errors.append("LOCAL_PGVECTOR_NOT_READY")
    required = [value for key, value in checks.items() if key != "ambient_key_variable_exists"
                and (require_clean or key != "git_clean")]
    return {"status": "PASS" if all(required) and not errors else "BLOCKED", "checks": checks,
            "errors": errors, "paid_requests": 0, "key_source_for_later_run": "new manual secure prompt, not ambient/P2 history"}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--require-clean", action="store_true")
    args = parser.parse_args()
    try:
        result = check(require_clean=args.require_clean)
    except Exception:  # noqa: BLE001
        result = {"status": "BLOCKED", "errors": ["LOCAL_PREFLIGHT_FAILED"], "paid_requests": 0}
    print(json.dumps(result, indent=2))
    return 0 if result["status"] == "PASS" else 1


if __name__ == "__main__":
    raise SystemExit(main())
