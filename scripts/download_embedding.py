"""Explicit free pretrained model download; application startup stays offline."""
import argparse
from pathlib import Path

from research_pilot.vector import MODEL_NAME, ZH_MODEL_NAME, create_embedding


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache-dir", type=Path, default=Path("data/models"))
    parser.add_argument("--model", choices=[MODEL_NAME, ZH_MODEL_NAME], default=MODEL_NAME)
    args = parser.parse_args()
    model = create_embedding(args.cache_dir, args.model, local_files_only=False)
    vector = model.query("ResearchPilot local embedding verification")
    assert vector.shape == (model.dimensions,)
    print(f"Downloaded and ran {model.model_name}: {len(vector)} dimensions")


if __name__ == "__main__":
    main()
