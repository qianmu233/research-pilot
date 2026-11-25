"""Deterministic offline fixtures for demonstrating orchestration."""
import re

from .multi_schema import EnterpriseReport, ReviewDecision, SupervisorPlan, WorkerAssessment


def generate_mock(schema, payload: dict) -> dict:
    if schema is SupervisorPlan:
        question = payload["question"]
        comparison = re.search(r"(?:比较|对比)\s*(.+?)(?:[，,；;。]|在|的|$)", question)
        subjects = re.split(r"\s*(?:、|和|与|及| / | versus | vs\.? )\s*", comparison[1]) if comparison else []
        match = re.search(r"维度\s*[：:]\s*([^；;。]+)", payload["scope"])
        dimensions = re.split(r"\s*[、，,]\s*", match[1]) if match else ["资料要点"]
        dimensions = list(dict.fromkeys(d.strip()[:100] for d in dimensions if d.strip()))[:8]
        dimensions = dimensions or ["资料要点"]
        return {"subtasks": [
            {"objective": subject[:300], "scope": (payload["scope"] or question)[:300],
             "dimensions": dimensions, "constraints": [payload["scope"][:300]] if payload["scope"] else [],
             "queries": [subject[:300]]}
            for subject in (subjects or [question])[:payload["max_subtasks"]] if subject.strip()
        ]}
    if schema is WorkerAssessment:
        objective = payload["objective"]
        sources = [s for s in payload["sources"] if objective.casefold() in
                   (s["title"] + s["excerpt"]).casefold()]
        covered = [d for d in payload["dimensions"]
                   if any(d == "资料要点" or d in s["excerpt"] for s in sources)]
        missing = [d for d in payload["dimensions"] if d not in covered]
        return {"conclusion": "Mock：已按关键词收集候选摘录。" if sources else "Mock：缺少匹配摘录。",
                "source_ids": [s["source_id"] for s in sources], "covered_dimensions": covered,
                "open_questions": [f"缺少{d[:90]}材料" for d in missing[:5]],
                "next_queries": [f"{objective[:100]} {d}" for d in missing[:2]]}
    if schema is ReviewDecision:
        gaps, followups = [], []
        for item in payload["subtasks"]:
            missing = item["missing_dimensions"]
            if item["status"] != "completed" or missing:
                gaps.append(f"{item['objective'][:100]}：缺少{('、'.join(missing) or '可用证据')[:140]}")
                if missing:
                    followups.append({"subtask_id": item["id"], "reason": "补查缺失维度",
                                      "queries": [f"{item['objective'][:100]} {d}" for d in missing[:2]]})
        return {"sufficient": not gaps, "gaps": gaps, "conflicts": [], "followups": followups}
    if schema is EnterpriseReport:
        return {
            "title": "技术选型研究报告（Mock 摘录演示）",
            "answer_status": "answered" if payload["sufficient"] and payload["sources"] else
            "insufficient_evidence",
            "claims": [
                {"text": s["title"], "section": "comparison",
                 "source_id": s["source_id"], "quote": s["excerpt"][:180].strip()}
                for s in payload["sources"][:8] if s["excerpt"].strip()
            ],
            "limitations": ["Mock 只按关键词提取候选材料，未运行真实模型分析或事实核查。"],
        }
    raise ValueError("UNKNOWN_MULTI_SCHEMA")
