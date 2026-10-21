"""Only used with temporary acceptance databases; no production failure flags."""
import os
import sys
from pathlib import Path

from research_pilot.config import Settings
from research_pilot.model import MockResearchModel
from research_pilot.runtime import ResearchRuntime
from research_pilot.schema import CreateTask, IngestText


class CrashAtWrite(MockResearchModel):
    def draft(self, *args):
        os._exit(73)


data_dir = Path(sys.argv[1])
runtime = ResearchRuntime(Settings(data_dir=data_dir, min_evidence=1), model=CrashAtWrite())
runtime.ingest_text(IngestText(title="Crash acceptance", content=
                              "LangGraph durable checkpoints preserve state across process crashes."))
task_id = runtime.create_task(CreateTask(question="Explain LangGraph durable checkpoints"))
(data_dir / "task-id.txt").write_text(task_id)
runtime.run_task(task_id)
raise AssertionError("Crash injection was not reached")
