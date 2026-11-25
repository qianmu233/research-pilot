"""Crash the process after one of two real workers durably saves its result."""
import os
import sys
import time
from pathlib import Path

from research_pilot.config import Settings
from research_pilot.runtime import ResearchRuntime
from research_pilot.schema import CreateTask, IngestText

data_dir = Path(sys.argv[1])
runtime = ResearchRuntime(Settings(data_dir=data_dir, max_model_calls=8, multi_max_concurrency=2))
for name in ("alpha", "beta"):
    runtime.ingest_text(IngestText(title=name, content=f"{name} cost is documented in training fixtures."))
task_id = runtime.create_task(CreateTask(
    question="比较 alpha 和 beta 的部署方案", scope="维度：cost", mode="multi",
))
(data_dir / "task-id.txt").write_text(task_id)
original = runtime.local.search


def crash_when_peer_is_durable(query, limit):
    if query == "beta":
        deadline = time.monotonic() + 12
        while time.monotonic() < deadline:
            if any(c["objective"] == "alpha" and c["status"] == "completed"
                   for c in runtime.store.subtasks(task_id)):
                os._exit(79)
            time.sleep(0.02)
        raise AssertionError("Peer did not finish")
    return original(query, limit)


runtime.local.search = crash_when_peer_is_durable
runtime.run_task(task_id)
raise AssertionError("Crash injection was not reached")
