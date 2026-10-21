"""Run the frozen Phase 6 dataset on the current BGE model and real PgVector."""
import argparse
import json
import os
import time
from pathlib import Path

from research_pilot.benchmark import load_dataset, run_benchmark
from research_pilot.vector import MODEL_NAME, ZH_MODEL_NAME, create_embedding

DEMO_DSN = ("postgresql://researchpilot_demo:researchpilot_local_demo"
            "@127.0.0.1:15432/researchpilot_demo")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset", type=Path,
                        default=Path("benchmarks/zh_retrieval_v1/dataset.json"))
    parser.add_argument("--cache-dir", type=Path, default=Path("data/models"))
    parser.add_argument("--label", required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--model", choices=[MODEL_NAME, ZH_MODEL_NAME], default=MODEL_NAME)
    parser.add_argument("--query-instruction", action="store_true")
    parser.add_argument("--collection")
    parser.add_argument("--keep-index", action="store_true")
    args = parser.parse_args()
    if args.output.exists():
        raise FileExistsError("Preserve existing benchmark evidence; choose another output file")
    dataset, digest = load_dataset(args.dataset)
    started = time.perf_counter()
    embedding = create_embedding(args.cache_dir, args.model, query_instruction=args.query_instruction)
    load_seconds = time.perf_counter()-started
    result = run_benchmark(dataset, digest, embedding,
                           os.getenv("RESEARCH_TEST_POSTGRES_DSN", DEMO_DSN), args.label,
                           collection=args.collection, keep_index=args.keep_index)
    result["performance"]["model_load_seconds"] = load_seconds
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({k: result[k] for k in ("query_count", "production_metrics",
                                            "evidence_checks", "truncation_probe")},
                     ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
