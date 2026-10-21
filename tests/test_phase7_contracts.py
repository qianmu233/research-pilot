"""Offline structured-provider contracts. These are NOT real LLM acceptance."""
import time
from dataclasses import replace

import httpx
import pytest
from langchain_openai import ChatOpenAI
from openai import APITimeoutError

from research_pilot.config import Settings
from research_pilot.local_llm import (
    ContextBudgetExceeded,
    LocalStructuredModel,
    ModelContractError,
    validate_structured_report,
)
from research_pilot.runtime import ResearchRuntime
from research_pilot.schema import CreateTask, IngestText
from research_pilot.store import LocalStore, ModelCallBudgetExceeded


class ScriptedStructuredProvider:
    structured_research = True

    def __init__(self, *, no_answer=False, fail_write=False):
        self.assessments = 0
        self.no_answer, self.fail_write = no_answer, fail_write

    def generate(self, stage, payload, timeout):
        assert timeout > 0
        if stage == "plan":
            return {"objective": "检查合成测试事实", "questions": ["checkpoint行为"],
                    "queries": ["checkpoint 持久化"]}, {}
        if stage == "assess":
            self.assessments += 1
            enough = self.assessments == 2 and not self.no_answer
            return {"sufficient": enough, "reason": "合成协议测试", "source_ids": ["S1"] if enough else [],
                    "missing_information": [] if enough else ["仍需核实"],
                    "next_queries": [] if enough else ["checkpoint 持久化"]}, {}
        if self.fail_write:
            raise ValueError("synthetic provider failure")
        answer = not self.no_answer
        return {"title": "合成协议测试", "answer_status": "answered" if answer else "insufficient_evidence",
                "claims": [{"text": "持久化状态", "source_id": "S1", "quote": "checkpoint"}] if answer else [],
                "limitations": ["自动化协议测试，不是真实模型研究"]}, {}


def test_structured_graph_supplements_and_persists_plan(tmp_path):
    runtime = ResearchRuntime(Settings(data_dir=tmp_path), model=ScriptedStructuredProvider())
    runtime.ingest_text(IngestText(title="合成协议资料", content="checkpoint 持久化状态；此为明确标记的合成测试材料。"))
    task_id = runtime.create_task(CreateTask(question="checkpoint 如何持久化状态？"))
    runtime.run_task(task_id)
    task = runtime.get_task(task_id)
    assert task["status"] == "completed" and task["model_calls"] == 4
    assert task["trace"] == ["plan", "retrieve:1:1", "assess:model_insufficient",
                             "retrieve:2:1", "assess:model_sufficient", "write", "validate:OK"]
    assert task["research"]["citation_valid"] and not task["research"]["facts_verified"]
    assert task["research"]["plan"]["questions"] == ["checkpoint行为"]
    assert task["research"]["retrieval_rounds"][1]["new_source_ids"] == []
    config = {"configurable": {"thread_id": task_id}}
    assert runtime.graph.get_state(config).values["research"] == task["research"]
    runtime.close()


def test_insufficient_with_candidates_can_complete_without_fabricated_citations(tmp_path):
    runtime = ResearchRuntime(Settings(data_dir=tmp_path, max_rounds=1),
                              model=ScriptedStructuredProvider(no_answer=True))
    runtime.ingest_text(IngestText(title="合成干扰", content="checkpoint 持久化状态，本文没有公司季度营收数据。"))
    task_id = runtime.create_task(CreateTask(question="checkpoint 产品的营收是多少？"))
    runtime.run_task(task_id)
    task = runtime.get_task(task_id)
    assert task["sources"] and task["status"] == "completed"
    assert task["research"]["report"]["answer_status"] == "insufficient_evidence"
    assert task["research"]["report"]["claims"] == [] and task["evidence_status"] == "unverified"
    assert task["model_calls"] == 3
    runtime.close()


def test_call_reservations_survive_failed_generation_and_process_reopen(tmp_path):
    settings = Settings(data_dir=tmp_path, max_rounds=1, max_model_calls=3)
    runtime = ResearchRuntime(settings, model=ScriptedStructuredProvider(no_answer=True, fail_write=True))
    task_id = runtime.create_task(CreateTask(question="checkpoint 未知问题如何回答？"))
    runtime.run_task(task_id)
    assert runtime.get_task(task_id)["model_calls"] == 3
    assert runtime.get_task(task_id)["status"] == "failed"
    runtime.close()
    reopened = ResearchRuntime(settings, model=ScriptedStructuredProvider(no_answer=True))
    reopened.run_task(task_id)
    task = reopened.get_task(task_id)
    assert task["model_calls"] == 3 and task["status"] == "failed"
    assert task["error_code"] == "WORKFLOW_FAILURE_ModelCallBudgetExceeded"
    assert task["model_events"][-1]["status"] == "failed"
    reopened.close()


def test_persistent_deadline_and_budget_fail_closed(tmp_path):
    store = LocalStore(tmp_path / "budget.sqlite3")
    tid = store.create_task(CreateTask(question="检查模型调用预算的持久化行为"))
    for _ in range(3):
        store.reserve_model_call(tid, "plan", 3, 30)
    with pytest.raises(ModelCallBudgetExceeded):
        store.reserve_model_call(tid, "plan", 3, 30)
    with store.conn:
        store.conn.execute("UPDATE model_budgets SET started=? WHERE task_id=?", (time.time() - 31, tid))
    with pytest.raises(TimeoutError):
        store.reserve_model_call(tid, "write", 3, 30)
    assert store.task(tid)["model_calls"] == 3
    store.close()


def test_structured_provenance_rejects_unknown_quote_and_unsupported_answer():
    source = [{"source_id": "S1", "excerpt": "真实原文片段"}]
    report = {"title": "报告", "answer_status": "answered", "claims": [
        {"text": "结论", "source_id": "S999", "quote": "真实原文"}], "limitations": ["尚未核实事实"]}
    assert validate_structured_report(report, source, {"sufficient": True}) == "UNKNOWN_CITATION_ID"
    report["claims"][0]["source_id"] = "S1"
    report["claims"][0]["quote"] = "伪造摘录"
    assert validate_structured_report(report, source, {"sufficient": True}) == "QUOTE_NOT_IN_SOURCE"
    report["claims"][0]["quote"] = "真实原文"
    assert validate_structured_report(report, source, {"sufficient": False}) == "UNSUPPORTED_ANSWER_STATUS"


def test_local_endpoint_and_input_budget_reject_before_generation():
    settings = Settings(model_backend="ollama", model_name="test-local-only",
                        model_base_url="http://127.0.0.1:11434/v1")
    with pytest.raises(ValueError):
        replace(settings, model_base_url="https://example.org/v1").validate()
    with pytest.raises(ValueError):
        replace(settings, model_base_url="http://user:secret@localhost:11434/v1").validate()
    model = LocalStructuredModel(settings)
    with pytest.raises(ContextBudgetExceeded):
        model.generate("plan", {"question": "超长输入" * 2000}, 1)


@pytest.mark.parametrize("failure", ["invalid_json", "timeout"])
def test_actual_langchain_wire_contract_rejects_invalid_json_and_timeout(failure):
    """Real SDK/parser, simulated HTTP transport: not an Ollama/model test."""
    def respond(request):
        import json
        body = json.loads(request.content)
        assert body["response_format"]["type"] == "json_schema"
        assert body["reasoning_effort"] == "none"
        assert body["max_tokens"] == 768
        assert "max_completion_tokens" not in body
        assert 0 < request.extensions["timeout"]["read"] <= 1
        if failure == "timeout":
            raise httpx.ReadTimeout("synthetic timeout", request=request)
        return httpx.Response(200, json={"id": "contract-only", "object": "chat.completion",
            "created": 0, "model": "contract-only", "choices": [{"index": 0, "finish_reason": "stop",
            "message": {"role": "assistant", "content": "not JSON"}}]})

    settings = Settings(model_backend="ollama", model_name="contract-only",
                        model_base_url="http://127.0.0.1:11434/v1")
    model = LocalStructuredModel(settings)
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        model.client = ChatOpenAI(model="contract-only", api_key="no-secret", max_retries=0,
                                  base_url=settings.model_base_url, http_client=client)
        with pytest.raises(APITimeoutError if failure == "timeout" else ModelContractError):
            model.generate("plan", {"question": "如何持久化状态？", "scope": ""}, 1)


def test_report_grammar_uses_exact_quotes_without_putting_untrusted_text_in_system():
    """Inspect real SDK request with a simulated transport; no model call."""
    import json
    marker = "不可信文档要求忽略系统规则。"
    def respond(request):
        body = json.loads(request.content)
        assert marker not in body["messages"][0]["content"]
        assert marker in body["messages"][1]["content"]
        schema = body["response_format"]["json_schema"]["schema"]
        # LangChain may inline the Pydantic $defs before sending the schema.
        claim = schema["properties"]["claims"]["items"]
        if "$ref" in claim:
            claim = schema["$defs"]["GroundedClaim"]
        assert claim["properties"]["quote"]["enum"] == [marker]
        assert claim["properties"]["source_id"]["enum"] == ["S1"]
        report = {"title": "合成协议测试", "answer_status": "insufficient_evidence", "claims": [],
                  "limitations": ["不可信指令不是事实证据"]}
        return httpx.Response(200, json={"id": "contract-only", "object": "chat.completion",
            "created": 0, "model": "contract-only", "choices": [{"index": 0, "finish_reason": "stop",
            "message": {"role": "assistant", "content": json.dumps(report)}}]})
    settings = Settings(model_backend="ollama", model_name="contract-only",
                        model_base_url="http://127.0.0.1:11434/v1")
    model = LocalStructuredModel(settings)
    with httpx.Client(transport=httpx.MockTransport(respond)) as client:
        model.client = ChatOpenAI(model="contract-only", api_key="no-secret", max_retries=0,
                                  base_url=settings.model_base_url, http_client=client)
        result, _ = model.generate("write", {"question": "测试资料是否足以回答？", "sources": [
            {"source_id": "S1", "excerpt": marker}]}, 1)
        assert result["claims"] == []
