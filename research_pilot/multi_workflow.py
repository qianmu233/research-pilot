"""Supervisor/Worker coordination using LangGraph Send and durable worker cursors."""
from __future__ import annotations

import hashlib
import html
import itertools
import json
import re
import time
from typing import Annotated, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import Send, interrupt
from openai import LengthFinishReasonError

from .evidence import merge_sources, validate_citations
from .local_llm import (
    ContextBudgetExceeded,
    ModelContractError,
    ProviderFailure,
    evidence_payload,
    validate_structured_report,
)
from .multi_schema import EnterpriseReport, ReviewDecision, SupervisorPlan
from .research_agent import MAX_ATTEMPTS, RETRYABLE, build_worker, missing_dimensions, new_queries
from .store import ModelCallBudgetExceeded

SECTIONS = {
    "candidates": "候选技术方案",
    "comparison": "多维度方案对比",
    "fit": "适用条件",
    "risks": "成本、风险及限制",
    "recommendation": "综合选型建议",
}


def merge_results(previous: dict, incoming: dict) -> dict:
    merged = {**previous}
    for subtask_id, result in incoming.items():
        saved = merged.get(subtask_id)
        if not saved or (result["generation"], result["attempts"]) > (
            saved["generation"], saved["attempts"]
        ):
            merged[subtask_id] = result
    return merged


class MultiState(TypedDict, total=False):
    task_id: str
    question: str
    scope: str
    limits: dict
    specs: list[dict]
    assignments: dict[str, dict]
    results: Annotated[dict[str, dict], merge_results]
    supplemented: bool
    sources: list[dict]
    tool_errors: list[str]
    evidence_status: str
    report: str
    report_status: str
    research: dict
    trace: list[str]


def execution_limits(settings) -> dict:
    return {key: getattr(settings, key) for key in (
        "max_model_calls", "task_timeout_seconds", "step_timeout_seconds", "max_rounds",
        "max_sources", "multi_max_subtasks", "multi_max_concurrency",
    )}


def comparison_targets(question: str) -> list[str]:
    """Recognize an explicit list of product identifiers before the comparison topic."""
    name = r"[A-Za-z][A-Za-z0-9_.+-]{0,49}"
    separator = r"\s*(?:、|，|,|和|与|及|/|\band\b|\bvs\b)\s*"
    match = re.search(rf"(?:比较|对比)\s*({name}(?:{separator}{name})+)(?=\s*(?:在|的|[。；？]|$))",
                      question, re.IGNORECASE)
    return list(dict.fromkeys(re.split(separator, match[1], flags=re.IGNORECASE))) if match else []


def requested_dimensions(scope: str) -> list[str]:
    match = re.search(r"维度\s*[：:]\s*([^；;。]+)", scope)
    if not match:
        return []
    dimensions = list(dict.fromkeys(part.strip() for part in re.split(r"[、，,]", match[1]) if part.strip()))
    return dimensions if len(dimensions) <= 8 and all(len(part) <= 100 for part in dimensions) else []


def plan_specs(task_id: str, plan: SupervisorPlan, limit: int, *, targets=(),
               dimensions=(), scope="") -> list[dict]:
    if len(plan.subtasks) > limit:
        raise ModelContractError("SUPERVISOR_SUBTASK_LIMIT")
    specs = {}
    planned = [item.model_dump() for item in plan.subtasks]
    if targets and len(targets) <= limit:
        by_target = {}
        for spec in planned:
            matches = [target for target in targets if re.search(
                rf"(?<![A-Za-z0-9_.+-]){re.escape(target)}(?![A-Za-z0-9_.+-])",
                spec["objective"], re.IGNORECASE
            )]
            if len(matches) == 1:
                by_target.setdefault(matches[0], spec)
        planned = [
            {"objective": target, "scope": scope[:300] or by_target.get(target, {}).get("scope", target),
             "dimensions": list(dimensions) or by_target.get(target, {}).get("dimensions", ["资料要点"]),
             "constraints": by_target.get(target, {}).get("constraints", []), "queries": [target],
             "search_target": target}
            for target in targets
        ]
    for spec in planned:
        spec["dimensions"] = list(dict.fromkeys(spec["dimensions"]))
        identity = json.dumps([spec["objective"].casefold(), spec["scope"].casefold(),
                               sorted(d.casefold() for d in spec["dimensions"])],
                              ensure_ascii=False)
        subtask_id = "R-" + hashlib.sha256(f"{task_id}:{identity}".encode()).hexdigest()[:20]
        specs.setdefault(subtask_id, {"id": subtask_id, **spec})
    return list(specs.values())


def collect_evidence(specs: list[dict], results: dict, limit: int) -> list[dict]:
    # Interleave in plan order before assigning global IDs, independent of thread completion.
    pools = []
    for spec in specs:
        result = results[spec["id"]]
        cited = set(result.get("source_ids", []))
        pools.append(sorted(result["sources"], key=lambda source: source["source_id"] not in cited))
    candidates = [source for batch in itertools.zip_longest(*pools)
                  for source in batch if source is not None]
    return merge_sources([], candidates, limit)


def summarize_workers(state: MultiState) -> tuple[list[dict], list[str]]:
    summaries, gaps = [], []
    global_ids = {(s["locator"], s["excerpt"]): s["source_id"] for s in state["sources"]}
    for spec in state["specs"]:
        result = state["results"][spec["id"]]
        missing = missing_dimensions(spec, result)
        retained = [global_ids[(s["locator"], s["excerpt"])] for s in result["sources"]
                    if (s["locator"], s["excerpt"]) in global_ids]
        cited = {s["source_id"] for s in result["sources"] if
                 (s["locator"], s["excerpt"]) in global_ids}
        label = spec["objective"][:90]
        if missing:
            gaps.append(f"{label}：尚缺覆盖维度 {'、'.join(missing)[:160]}。")
        if result["status"] != "completed":
            code = result.get("error_code") or result["status"]
            gaps.append(f"{label}：子任务状态 {code}。")
        if set(result.get("source_ids", [])) - cited:
            gaps.append(f"{label}：部分引用证据未进入全局证据集合。")
        summaries.append({
            "id": spec["id"], "objective": label, "status": result["status"],
            "source_ids": retained, "missing_dimensions": missing,
            "covered_dimensions": result.get("covered_dimensions", []),
            "conclusion": result.get("conclusion", "")[:160],
            "open_questions": [q[:100] for q in result.get("open_questions", [])[:3]],
        })
    return summaries, gaps


def model_sources(sources: list[dict], excerpt_limit: int) -> list[dict]:
    allowance = min(excerpt_limit, 2000 // max(1, len(sources)))
    return [{**source, "excerpt": source["excerpt"][:allowance]}
            for source in evidence_payload(sources)]


def render_enterprise(report: EnterpriseReport, sources: list[dict], gaps: list[str],
                      question: str, scope: str) -> str:
    lines = [f"# {report.title}", "", "## 调研背景与业务需求", "",
             f"证据结论：{report.answer_status}。", ""]
    for value in (question, scope):
        if value:
            lines.extend(f"> {html.escape(line).replace('[', '&#91;')}" for line in value.splitlines())
            lines.append("")
    for section, title in SECTIONS.items():
        claims = [c for c in report.claims if c.section == section]
        if claims:
            lines.extend(["", f"## {title}", "",
                          *[f"- {c.text} [{c.source_id}]" for c in claims]])
    lines.extend(["", "## 证据不足与待确认事项", ""])
    lines.extend(f"- {item}" for item in dict.fromkeys(report.limitations + gaps))
    if report.claims:
        lines.extend(["", "## 参考来源及原文引用", ""])
        allowed = {s["source_id"]: s for s in sources}
        for source_id, quote in dict.fromkeys((claim.source_id, claim.quote) for claim in report.claims):
            source = allowed.get(source_id, {})
            lines.append(f"- [{source_id}] {source.get('title', '')}：{quote}")
    return "\n".join(lines)


def build_multi_graph(model, tools, checkpointer, store, io, interrupt_before=None):
    def generate(state, stage, schema, instruction, payload, *, subtask_id=None, keep_calls=0):
        limits = state["limits"]
        number, remaining = store.reserve_model_call(
            state["task_id"], stage, limits["max_model_calls"], limits["task_timeout_seconds"],
            subtask_id=subtask_id, keep_calls=keep_calls,
        )
        timeout = min(remaining, limits["step_timeout_seconds"])
        started = time.monotonic()
        status, usage = "failed", {}
        try:
            raw, usage = io.call(timeout, lambda remaining:
                                 model.generate_multi(schema, instruction, payload, remaining))
            if time.monotonic() - started >= timeout:
                raise TimeoutError("MODEL_DEADLINE_EXCEEDED")
            parsed = schema.model_validate(raw, strict=True)
            status = "completed"
            return parsed
        except LengthFinishReasonError as exc:
            tokens = exc.completion.usage
            usage = {"finish_reason": "length"}
            if tokens is not None:
                usage.update(input_tokens=tokens.prompt_tokens, output_tokens=tokens.completion_tokens,
                             total_tokens=tokens.total_tokens)
            raise ProviderFailure("MODEL_OUTPUT_TRUNCATED", usage) from None
        except ModelContractError as exc:
            if str(exc) == "MODEL_OUTPUT_TRUNCATED":
                raise ProviderFailure("MODEL_OUTPUT_TRUNCATED", {"finish_reason": "length"}) from None
            raise
        except Exception as exc:
            usage = getattr(exc, "usage", usage)
            raise
        finally:
            store.finish_model_call(state["task_id"], number, status,
                                    time.monotonic() - started, usage)

    worker = build_worker(tools, store, generate, io)

    def append(state, phase):
        return [*state.get("trace", []), phase]

    def supervisor(state: MultiState) -> dict:
        limit = state["limits"]["multi_max_subtasks"]
        targets = comparison_targets(state["question"])
        dimensions = requested_dimensions(state["scope"])
        plan = generate(
            state, "supervisor", SupervisorPlan,
            "动态拆分企业研究问题。比较具名候选时优先按候选拆分，每个候选的所有要求维度放在同一子任务中，"
            "首条查询使用候选名称。没有具名候选时按相互独立的主题拆分。"
            "集中对比由汇总节点完成，计划中不要额外添加综合对比任务或重复候选。"
            "沿用用户的维度名称与约束，不新增技术指标、法规或时间限制。最多max_subtasks个子任务。",
            {"question": state["question"], "scope": state["scope"], "max_subtasks": limit,
             "explicit_targets": targets, "explicit_dimensions": dimensions},
            keep_calls=2,
        )
        specs = plan_specs(state["task_id"], plan, limit, targets=targets,
                           dimensions=dimensions, scope=state["scope"])
        assignments = {spec["id"]: {"generation": 0, "queries": spec["queries"]} for spec in specs}
        return {"specs": specs, "assignments": assignments,
                "trace": append(state, f"supervisor:{len(specs)}")}

    def dispatch(state: MultiState) -> dict:
        store.register_subtasks(state["task_id"], state["specs"])
        phase = "supplement" if state.get("supplemented") else "research"
        return {"trace": append(state, f"{phase}:{len(state['assignments'])}")}

    def sends(state: MultiState) -> list[Send]:
        return [
            Send("worker", {"task_id": state["task_id"], "limits": state["limits"], "spec": spec,
                            "assignment": state["assignments"][spec["id"]]})
            for spec in state["specs"] if spec["id"] in state["assignments"]
        ]

    def research(work: dict) -> dict:
        assignment = work["assignment"]
        result = worker({k: work[k] for k in ("task_id", "limits", "spec")}, assignment)
        return {"results": {work["spec"]["id"]: result}}

    def collect(state: MultiState) -> dict:
        sources = collect_evidence(state["specs"], state["results"], state["limits"]["max_sources"])
        errors = list(dict.fromkeys(error for result in state["results"].values()
                                    for error in result.get("errors", [])))
        return {"sources": sources, "tool_errors": errors,
                "evidence_status": "unverified" if sources else "no_evidence",
                "trace": append(state, f"merge:{len(sources)}")}

    def still_in_time(state):
        try:
            store.check_task_deadline(state["task_id"], state["limits"]["task_timeout_seconds"])
        except TimeoutError:
            return False
        return True

    def retry_ids(state):
        return [key for key, result in state["results"].items()
                if result["status"] in RETRYABLE and result["attempts"] < MAX_ATTEMPTS
                and key in state["assignments"]]

    def after_collect(state):
        return "recover" if retry_ids(state) and still_in_time(state) else "review"

    def recover(state: MultiState) -> dict:
        pending = retry_ids(state)
        interrupt({"reason": "WORKER_RETRY_AVAILABLE", "subtask_ids": sorted(pending)})
        assignments = {key: state["assignments"][key] for key in pending} if still_in_time(state) else {}
        return {"assignments": assignments, "trace": append(state, f"recovery:{len(assignments)}")}

    def review(state: MultiState) -> dict:
        summaries, gaps = summarize_workers(state)
        focused_queries = {}
        for spec in state["specs"]:
            target = spec.get("search_target")
            if target:
                result = state["results"][spec["id"]]
                missing = set(missing_dimensions(spec, result))
                evidence_text = "\n".join(source["excerpt"] for source in result["sources"]).casefold()
                # A literal mismatch is a search hint, not proof that a dimension is unsupported.
                hints = [d for d in spec["dimensions"] if d.casefold() not in evidence_text]
                hints.extend(d for d in spec["dimensions"] if d in missing and d not in hints)
                if hints:
                    focused_queries[spec["id"]] = [f"{target} {dimension}" for dimension in hints[:2]]
        decision = None
        conflicts = []
        assignments = {}
        followups = []
        rejected_followups = 0
        try:
            decision = generate(
                state, "review", ReviewDecision,
                "只按原问题和范围检查候选及维度。明确需要后续实测或确认本身可以是有效发现。"
                "不要将用户未要求的性能指标、法规、集成细节列作缺口。对同一事实的相反表述才是冲突。"
                "review_queries列出局部已识别的缺口。优先对这些任务补查，保持查询词简短。"
                "资料已说明试点如何安排时，未给通用实测数值可列为局限，无须补查。"
                "followups只用现有任务ID和用户已要求的维度。"
                "有缺口或冲突时sufficient为false。最多列3项缺口、2项冲突、3项补查；每项用短句。",
                {"question": state["question"], "scope": state["scope"], "subtasks": summaries,
                 "review_queries": focused_queries, "sources": model_sources(state["sources"], 450)},
                keep_calls=1,
            )
        except ModelCallBudgetExceeded:
            gaps.append("调用额度已保留给报告，未完成本轮全局评估。")
        except TimeoutError:
            gaps.append("评估达到时间上限，未完成本轮全局评估。")
        except ContextBudgetExceeded:
            gaps.append("输入超过模型上下文限制，未完成本轮全局评估。")
        except ProviderFailure as exc:
            if exc.code != "MODEL_OUTPUT_TRUNCATED":
                raise
            gaps.append("全局评估输出达到长度上限，使用已有子任务结果披露缺口。")
        if decision is not None:
            followups = [item for item in decision.followups if item.subtask_id in state["results"]]
            rejected_followups = len(decision.followups) - len(followups)
            if rejected_followups:
                gaps.append("全局评估引用了未知子任务，相关补查未执行。")
            gaps.extend(decision.gaps)
            conflicts = decision.conflicts
            gaps.extend(f"模型标记的潜在资料冲突（待核对）：{item}" for item in conflicts)
            if not state.get("supplemented") and still_in_time(state):
                # Align exploratory query wording with known coverage gaps. The review still
                # controls whether supplementation is needed and owns the no-follow-up path.
                candidates = {item.subtask_id: (item.queries, item.reason) for item in reversed(followups)}
                if candidates and focused_queries:
                    candidates = {key: (queries, "补查未覆盖的请求维度")
                                  for key, queries in focused_queries.items()}
                for subtask_id, (queries, reason) in candidates.items():
                    result = state["results"][subtask_id]
                    if result["status"] in RETRYABLE or len(result["rounds"]) >= state["limits"]["max_rounds"]:
                        continue
                    fresh = new_queries(queries, result["rounds"])
                    if fresh:
                        assignments[subtask_id] = {"generation": 1, "queries": fresh, "reason": reason}
            if not decision.sufficient or decision.followups:
                gaps.append("全局评估尚有未解决的研究要求。")
        sufficient = bool(decision and decision.sufficient and not gaps and state["sources"])
        if not state["sources"]:
            gaps.append("资料库没有返回可引用的证据。")
        research = {**state.get("research", {}),
                    "review": {"sufficient": sufficient, "gaps": list(dict.fromkeys(gaps)),
                               "conflicts": conflicts,
                               "followups": [item.model_dump() for item in followups],
                               "rejected_followup_count": rejected_followups},
                    "citation_valid": False, "facts_verified": False}
        return {"research": research, "assignments": assignments,
                "supplemented": bool(assignments) or state.get("supplemented", False),
                "trace": append(state, "review:sufficient" if sufficient else "review:insufficient")}

    def write(state: MultiState) -> dict:
        review = state["research"]["review"]
        sources = model_sources(state["sources"], 700)
        try:
            report = generate(
                state, "multi_write", EnterpriseReport,
                "写中文企业技术选型报告。每项结论必须附原文摘录和匹配的来源ID。"
                "按候选、对比、适用条件、风险或建议分类。只有证据支持时才给建议。"
                "不得编造性能、费用或实验；sufficient为false时答复insufficient_evidence。"
                "整体不足时仍逐条保留有摘录支持的局部发现。只有没有任何可支持的发现才将claims留空。"
                "quote只能选用quote_options的完整字符串。优先呈现4条简短关键结论，每条text限一句。",
                {"question": state["question"], "scope": state["scope"],
                 "sufficient": review["sufficient"], "gaps": [g[:150] for g in review["gaps"][:6]],
                 "sources": sources},
            )
        except (ModelCallBudgetExceeded, TimeoutError, ContextBudgetExceeded, ProviderFailure) as exc:
            if isinstance(exc, ProviderFailure) and exc.code != "MODEL_OUTPUT_TRUNCATED":
                raise
            report = EnterpriseReport.model_validate({
                "title": "研究报告未形成获证结论", "answer_status": "insufficient_evidence",
                "claims": [],
                "limitations": ["报告生成达到预算、时间、上下文或输出长度上限，候选来源可在任务结果中查看。"],
            })
        markdown = render_enterprise(report, state["sources"], review["gaps"],
                                     state["question"], state["scope"])
        return {"report": markdown, "trace": append(state, "write"),
                "research": {**state["research"], "report": report.model_dump()}}

    def validate(state: MultiState) -> dict:
        research = state["research"]
        report = EnterpriseReport.model_validate(research["report"])
        reason = validate_structured_report(report, state["sources"], research["review"])
        if reason == "OK":
            ok, reason = validate_citations(state["report"], state["sources"])
            if reason == "MISSING_CITATIONS" and not report.claims and report.answer_status == "insufficient_evidence":
                ok, reason = True, "OK"
        else:
            ok = False
        quality = "insufficient" if not state["sources"] else (
            "full" if report.answer_status == "answered" else "partial"
        )
        return {"report_status": "completed" if ok else "failed",
                "trace": append(state, f"validate:{reason}"),
                "research": {**research, "quality": quality if ok else "invalid",
                             "citation_valid": ok, "validation_reason": reason}}

    builder = StateGraph(MultiState)
    for name, fn in (("supervisor", supervisor), ("dispatch", dispatch), ("worker", research),
                     ("collect", collect), ("recover", recover), ("review", review),
                     ("write", write), ("validate", validate)):
        builder.add_node(name, fn)
    builder.add_edge(START, "supervisor")
    builder.add_edge("supervisor", "dispatch")
    builder.add_conditional_edges("dispatch", sends, ["worker"])
    builder.add_edge("worker", "collect")
    builder.add_conditional_edges("collect", after_collect, ["recover", "review"])
    builder.add_conditional_edges("recover", lambda state: "dispatch" if state["assignments"] else "review",
                                  ["dispatch", "review"])
    builder.add_conditional_edges("review", lambda state: "dispatch" if state["assignments"] else "write",
                                  ["dispatch", "write"])
    builder.add_edge("write", "validate")
    builder.add_edge("validate", END)
    return builder.compile(checkpointer=checkpointer, interrupt_before=interrupt_before)
