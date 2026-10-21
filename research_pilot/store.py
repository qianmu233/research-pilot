"""SQLite task and document stores. SQLite remains local-demo storage, not HA."""
from __future__ import annotations

import json
import sqlite3
import threading
import time
import uuid
from datetime import UTC, datetime
from pathlib import Path

from .schema import CreateTask, IngestText

_UNSET = object()


def now_iso() -> str:
    return datetime.now(UTC).isoformat()


class LocalStore:
    def __init__(self, filename: Path):
        filename.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(filename), check_same_thread=False, timeout=10)
        self.conn.row_factory = sqlite3.Row
        self.lock = threading.RLock()
        with self.lock:
            self.conn.execute("PRAGMA journal_mode=WAL")
            self.conn.executescript("""
                CREATE TABLE IF NOT EXISTS tasks (
                  id TEXT PRIMARY KEY, question TEXT NOT NULL, scope TEXT NOT NULL,
                  status TEXT NOT NULL, phase TEXT NOT NULL,
                  created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                  error_code TEXT, report TEXT, sources_json TEXT NOT NULL DEFAULT '[]',
                  trace_json TEXT NOT NULL DEFAULT '[]'
                );
                CREATE TABLE IF NOT EXISTS chunks (
                  chunk_id TEXT PRIMARY KEY, doc_id TEXT NOT NULL,
                  title TEXT NOT NULL, source_ref TEXT NOT NULL, content TEXT NOT NULL
                );
            """)
            columns = {row[1] for row in self.conn.execute("PRAGMA table_info(tasks)")}
            if "tool_errors_json" not in columns:
                self.conn.execute("ALTER TABLE tasks ADD COLUMN tool_errors_json TEXT NOT NULL DEFAULT '[]'")
            if "evidence_status" not in columns:
                self.conn.execute("ALTER TABLE tasks ADD COLUMN evidence_status TEXT NOT NULL DEFAULT 'unassessed'")
            if "research_json" not in columns:
                self.conn.execute("ALTER TABLE tasks ADD COLUMN research_json TEXT NOT NULL DEFAULT '{}'")
            self.conn.execute("""CREATE TABLE IF NOT EXISTS model_budgets (
                task_id TEXT PRIMARY KEY, started REAL NOT NULL, calls INTEGER NOT NULL,
                events_json TEXT NOT NULL)""")

    def close(self) -> None:
        with self.lock:
            self.conn.close()

    def create_task(self, data: CreateTask) -> str:
        task_id = uuid.uuid4().hex
        timestamp = now_iso()
        with self.lock, self.conn:
            self.conn.execute(
                "INSERT INTO tasks(id,question,scope,status,phase,created_at,updated_at) VALUES (?,?,?,?,?,?,?)",
                (task_id, data.question, data.scope, "pending", "created", timestamp, timestamp),
            )
        return task_id

    def task(self, task_id: str) -> dict | None:
        with self.lock:
            row = self.conn.execute("SELECT * FROM tasks WHERE id=?", (task_id,)).fetchone()
        if row is None:
            return None
        item = dict(row)
        item["sources"] = json.loads(item.pop("sources_json"))
        item["trace"] = json.loads(item.pop("trace_json"))
        item["tool_errors"] = json.loads(item.pop("tool_errors_json"))
        item["research"] = json.loads(item.pop("research_json"))
        with self.lock:
            budget = self.conn.execute("SELECT * FROM model_budgets WHERE task_id=?", (task_id,)).fetchone()
        item["model_calls"] = budget["calls"] if budget else 0
        item["model_events"] = json.loads(budget["events_json"]) if budget else []
        return item

    def reserve_model_call(self, task_id: str, stage: str, max_calls: int,
                           timeout_seconds: float) -> tuple[int, float]:
        """Reserve BEFORE network I/O, persist even on crash/failure/resume. No retries."""
        with self.lock, self.conn:
            self.conn.execute("INSERT OR IGNORE INTO model_budgets VALUES (?,?,0,'[]')",
                              (task_id, time.time()))
            row = self.conn.execute("SELECT * FROM model_budgets WHERE task_id=?", (task_id,)).fetchone()
            remaining = timeout_seconds - (time.time() - row["started"])
            if remaining <= 0:
                raise TimeoutError("TASK_DEADLINE_EXCEEDED")
            if row["calls"] >= max_calls:
                raise ModelCallBudgetExceeded("MODEL_CALL_BUDGET_EXCEEDED")
            number = row["calls"] + 1
            events = json.loads(row["events_json"])
            events.append({"call": number, "stage": stage, "status": "reserved", "at": now_iso()})
            self.conn.execute("UPDATE model_budgets SET calls=?,events_json=? WHERE task_id=?",
                              (number, json.dumps(events), task_id))
        return number, remaining

    def check_task_deadline(self, task_id: str, timeout_seconds: float) -> None:
        with self.lock:
            row = self.conn.execute("SELECT started FROM model_budgets WHERE task_id=?", (task_id,)).fetchone()
        if row and time.time() - row[0] >= timeout_seconds:
            raise TimeoutError("TASK_DEADLINE_EXCEEDED")

    def finish_model_call(self, task_id: str, number: int, status: str, elapsed: float,
                          usage: dict) -> None:
        with self.lock, self.conn:
            row = self.conn.execute("SELECT events_json FROM model_budgets WHERE task_id=?", (task_id,)).fetchone()
            events = json.loads(row[0])
            events[number - 1].update(status=status, elapsed_seconds=round(elapsed, 4), **usage)
            self.conn.execute("UPDATE model_budgets SET events_json=? WHERE task_id=?",
                              (json.dumps(events), task_id))

    def patch_task(self, task_id: str, *, status: str | None = None,
                   phase: str | None = None, report: str | None = None,
                   error_code: str | None | object = _UNSET, sources: list | None = None,
                   trace: list[str] | None = None, tool_errors: list[str] | None = None,
                   evidence_status: str | None = None, research: dict | None = None) -> None:
        fields = {"updated_at": now_iso()}
        if status is not None:
            fields["status"] = status
        if phase is not None:
            fields["phase"] = phase
        if evidence_status is not None:
            fields["evidence_status"] = evidence_status
        if report is not None:
            fields["report"] = report
        if research is not None:
            fields["research_json"] = json.dumps(research, ensure_ascii=False)
        if error_code is not _UNSET:
            fields["error_code"] = error_code
        if sources is not None:
            fields["sources_json"] = json.dumps(sources, ensure_ascii=False)
        if trace is not None:
            fields["trace_json"] = json.dumps(trace, ensure_ascii=False)
        if tool_errors is not None:
            fields["tool_errors_json"] = json.dumps(tool_errors)
        with self.lock, self.conn:
            self.conn.execute(
                "UPDATE tasks SET " + ",".join(f"{key}=?" for key in fields) + " WHERE id=?",
                (*fields.values(), task_id),
            )

    def ingest_text(self, document: IngestText, chunk_size: int = 700) -> tuple[str, int]:
        doc_id = uuid.uuid4().hex
        # Minimal deterministic character chunker; NOT a tokenizer-aware embedding chunker.
        paragraphs = [part.strip() for part in document.content.splitlines() if part.strip()]
        chunks: list[str] = []
        current = ""
        for paragraph in paragraphs:
            for i in range(0, len(paragraph), chunk_size):
                segment = paragraph[i:i + chunk_size]
                if current and len(current) + len(segment) + 1 > chunk_size:
                    chunks.append(current)
                    current = segment
                else:
                    current = (current + "\n" + segment).strip()
        if current:
            chunks.append(current)
        with self.lock, self.conn:
            self.conn.executemany(
                "INSERT INTO chunks(chunk_id,doc_id,title,source_ref,content) VALUES (?,?,?,?,?)",
                [(f"{doc_id}-{idx}", doc_id, document.title, document.source_ref, content)
                 for idx, content in enumerate(chunks)],
            )
        return doc_id, len(chunks)

    def list_chunks(self, limit: int = 5000) -> list[dict]:
        with self.lock:
            rows = self.conn.execute(
                "SELECT chunk_id, doc_id, title, source_ref, content FROM chunks ORDER BY rowid DESC LIMIT ?",
                (limit,),
            ).fetchall()
        return [dict(row) for row in rows]


class ModelCallBudgetExceeded(RuntimeError):
    pass
