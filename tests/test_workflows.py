"""Offline regression tests with isolated databases and deterministic model stubs."""
from datetime import datetime, timedelta
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from fastapi.testclient import TestClient
from langchain_core.language_models.fake_chat_models import FakeListChatModel

from agents.appointment_agent import AppointmentAgent
from agents.consultant_agent import ConsultantAgent
from agents.consultant.knowledge_retriever import KnowledgeRetriever
from agents.task_classification import AgentRouter, ClassificationProcessor, StateManager, UnrelatedHandler
from agents.user_behavior_agent import UserBehaviorAgent
from config.constants import SharedState, StateEnum
from db.models import UserBehavior
from services.knowledge_service import KnowledgeService
from services.user_behavior_service import UserBehaviorService


@pytest.fixture
def knowledge(tmp_path, monkeypatch):
    import services.knowledge_service as module
    service = KnowledgeService(f"sqlite:///{(tmp_path / 'knowledge.db').as_posix()}")
    service.default_knowledge = []
    monkeypatch.setattr(module, "embed_input", lambda text: [1.0, 0.0])
    monkeypatch.setattr(module, "get_knowledge_service", lambda: service)
    import agents.consultant.knowledge_retriever as retriever
    monkeypatch.setattr(retriever, "get_knowledge_service", lambda: service)
    yield service
    service.db_router.close()


@pytest.fixture
def appointment(monkeypatch):
    monkeypatch.setattr(AppointmentAgent, "_initialize_llm", lambda self: FakeListChatModel(responses=["{}"]))
    agent = AppointmentAgent()
    agent.appointment_database.save_appointment = Mock(return_value=True)
    agent.appointment_processor.agent_executor = SimpleNamespace(ainvoke=AsyncMock(return_value={"output": "预约已完成"}))
    return agent


def parse_next(agent, data):
    agent.input_parser.parse_stream = lambda *args: iter(["{}"])
    agent.input_parser.parse_data = lambda text: data


@pytest.mark.asyncio
async def test_incomplete_booking_preserves_fields_and_finishes(appointment):
    shared = SharedState()
    shared.value = StateEnum.APPOINTMENT
    appointment.set_shared_state(shared)
    parse_next(appointment, {"start_time": "2026-12-01 15:00", "project": "肩颈"})
    reply = "".join([x async for x in appointment.run_stream("明天下午三点肩颈按摩")])
    assert "[REPLY]" in reply
    assert appointment.appointment_history["start_time"] == "2026-12-01 15:00"
    assert not appointment.finished
    appointment.technician_finder.find_technician_with_thought = lambda *args: {"id": 1, "name": "测试技师", "gender": "女"}
    parse_next(appointment, {"duration": "30分钟", "gender": "女"})
    reply = "".join([x async for x in appointment.run_stream("30分钟，女技师")])
    assert "预约成功" in reply
    appointment.appointment_database.save_appointment.assert_called_once()
    assert shared.value == StateEnum.CLASSIFY
    assert appointment.appointment_history["start_time"] is None


@pytest.mark.asyncio
async def test_replacement_requires_confirmation(appointment):
    appointment.technician_finder.find_technician_with_thought = lambda *args: {
        "requires_confirmation": True,
        "original_technician": {"id": 1, "name": "原技师", "gender": "女", "strength": "轻柔"},
        "recommended_technician": {"id": 2, "name": "替代技师", "gender": "女", "strength": "轻柔"},
    }
    appointment.message_builder.create_technician_recommendation_message = lambda *args: "是否接受替代技师？"
    parse_next(appointment, {"technician_name": "原技师", "start_time": "2026-12-01 15:00", "duration": "30分钟", "project": "肩颈"})
    reply = "".join([x async for x in appointment.run_stream("预约原技师")])
    assert "是否接受" in reply
    assert appointment.appointment_history["awaiting_confirmation"]
    appointment.appointment_database.save_appointment.assert_not_called()
    parse_next(appointment, {"confirmation": "可以"})
    reply = "".join([x async for x in appointment.run_stream("可以")])
    assert "预约成功" in reply
    appointment.appointment_database.save_appointment.assert_called_once()


@pytest.mark.asyncio
async def test_unrelated_booking_message_returns_to_dispatch(appointment):
    shared = SharedState()
    shared.value = StateEnum.APPOINTMENT
    appointment.set_shared_state(shared)
    appointment.appointment_history["duration"] = "30分钟"
    appointment.unrelated_callback = AsyncMock(return_value="营业时间说明")
    parse_next(appointment, {"unrelated": True})
    reply = "".join([x async for x in appointment.run_stream("几点开门")])
    assert "营业时间说明" in reply
    assert shared.value == StateEnum.CLASSIFY
    assert appointment.appointment_history["duration"] == "30分钟"


class AppointmentStub:
    def set_shared_state(self, state):
        self.state = state

    async def run_stream(self, user_input):
        yield "预约:" + user_input


class ConsultationStub:
    def set_shared_state(self, state):
        self.state = state

    async def __aenter__(self):
        return self

    async def __aexit__(self, *args):
        pass

    async def consult_stream(self, task, *, intent_confirmed=False):
        self.confirmed = intent_confirmed
        yield "咨询:" + task
        self.state.value = StateEnum.CLASSIFY


def processor(category):
    state = StateManager()
    classifier = SimpleNamespace(classify_task=AsyncMock(return_value=category))
    router = AgentRouter(AppointmentStub(), ConsultationStub(), state)
    return ClassificationProcessor(classifier, state, router, UnrelatedHandler(state))


@pytest.mark.asyncio
async def test_collector_reuses_stream_and_continues_appointment_state():
    p = processor("appointment")
    assert "预约:预约按摩" in await p.process_task_sync("预约按摩")
    assert p.state_manager.is_in_appointment_flow()
    assert "预约:30分钟" in await p.process_task_sync("30分钟")
    p.task_classifier.classify_task.assert_awaited_once()


@pytest.mark.asyncio
async def test_routed_consultation_passes_confirmed_intent():
    p = processor("query")
    assert "咨询:多少钱" in await p.process_task_sync("多少钱")
    assert p.agent_router.consultant_agent.confirmed
    assert p.state_manager.should_classify()


@pytest.mark.asyncio
async def test_unknown_task_uses_fallback_and_resets_state():
    p = processor("other")
    assert "[REPLY][归类机器人]" in await p.process_task_sync("闲聊")
    assert p.state_manager.should_classify()


@pytest.mark.asyncio
async def test_shared_index_updates_and_empty_library(knowledge):
    first, second = KnowledgeRetriever(), KnowledgeRetriever()
    assert first.knowledge_service is second.knowledge_service is knowledge
    await first.initialize()
    assert await knowledge.add_document("旧价格80元", "价格")
    doc_id = knowledge.get_all_documents()[0]["id"]
    assert "旧价格" in (await second.search_knowledge("价格"))[0]["content"]
    assert await knowledge.update_document(doc_id, content="新价格90元")
    assert "新价格" in (await first.search_knowledge("价格"))[0]["content"]
    assert await knowledge.delete_document(doc_id)
    assert await second.search_knowledge("价格") == []
    assert knowledge.index is None
    knowledge.initialized = False
    knowledge.default_knowledge = [{"content": "不应重建", "category": "测试", "keywords": []}]
    await knowledge.initialize()
    assert knowledge.get_all_documents() == []


@pytest.mark.asyncio
async def test_initialization_is_idempotent(knowledge, monkeypatch):
    build = AsyncMock(wraps=knowledge._build_vector_index)
    monkeypatch.setattr(knowledge, "_build_vector_index", build)
    await knowledge.initialize()
    await knowledge.initialize()
    build.assert_awaited_once()


@pytest.mark.asyncio
async def test_trusted_intent_skips_second_classification(knowledge, monkeypatch):
    monkeypatch.setattr(ConsultantAgent, "_initialize_llm", lambda self: FakeListChatModel(responses=["价格是80元"]))
    agent = ConsultantAgent()
    check = AsyncMock(return_value=True)
    agent.consultation_classifier.is_consultation_related = check
    agent.consultation_processor._record_consultation_behavior = AsyncMock()
    reply = "".join([part async for part in agent.consult_stream("多少钱", intent_confirmed=True)])
    assert "80元" in reply
    check.assert_not_awaited()
    assert "80元" in await agent.consult("多少钱")
    check.assert_awaited_once()


@pytest.fixture
def behavior(tmp_path):
    service = UserBehaviorService(f"sqlite:///{(tmp_path / 'behavior.db').as_posix()}")
    yield service
    service.db_router.close()


def test_behavior_statistics_share_service_without_model(behavior, monkeypatch):
    def unexpected_model(self):
        raise AssertionError("Statistics must not construct a model")
    monkeypatch.setattr(UserBehaviorAgent, "_initialize_llm", unexpected_model)
    agent = UserBehaviorAgent(behavior_service=behavior)
    assert agent.pattern_analyzer.behavior_service is behavior
    tech = behavior.db_router.technicians.add_technician("测试技师", "女", "手法轻")
    for _ in range(2):
        assert agent.record_behavior("appointment", {"project": "肩颈", "duration": 30}, str(tech))
    analysis = agent.get_user_analysis()
    assert analysis["favorite_technician_id"] == tech
    assert analysis["favorite_service"] == "肩颈"
    assert analysis["favorite_duration"] == 30
    assert analysis["total_appointments"] == 2
    assert not analysis["should_send_reminder"]
    assert agent._llm is None


def test_reminder_threshold_and_user_isolation(behavior):
    for _ in range(2):
        behavior.record_behavior("returning", "appointment", {"project": "肩颈", "duration": 30})
    with behavior.db_router.session_manager.session_scope() as session:
        session.query(UserBehavior).update({UserBehavior.created_at: datetime.utcnow() - timedelta(days=40)})
    agent = UserBehaviorAgent(behavior_service=behavior)
    assert agent.get_user_analysis("returning")["should_send_reminder"]
    assert agent.get_user_analysis("another-user") is None


@pytest.mark.asyncio
async def test_new_user_reminder_needs_no_model(behavior):
    agent = UserBehaviorAgent(behavior_service=behavior)
    result = await agent.get_reminder_with_schedule()
    assert result["message"]
    assert result["technician_available_times"] == []
    assert agent._llm is None


@pytest.mark.asyncio
async def test_personalized_reminder_uses_injected_model(behavior, monkeypatch):
    import db
    tech = behavior.db_router.technicians.add_technician("测试技师", "女", "手法轻")
    behavior.record_behavior("default_user", "appointment", {"project": "肩颈", "duration": 30}, tech)
    monkeypatch.setattr(db, "TechnicianDBRouter", lambda: behavior.db_router.technicians)
    llm = SimpleNamespace(ainvoke=AsyncMock(return_value=SimpleNamespace(content="欢迎再次预约测试技师。")))
    agent = UserBehaviorAgent(behavior_service=behavior, llm=llm)
    assert "测试技师" in await agent.generate_personalized_reminder()
    assert "30分钟" in llm.ainvoke.call_args.args[0][0]["content"]


@pytest.fixture
def client(knowledge, monkeypatch, tmp_path):
    # Model construction is stubbed before importing the chat entry point.
    import config.model_provider as models
    monkeypatch.setattr(models, "create_chat_model", lambda **kwargs: FakeListChatModel(responses=["{}", "query"]))
    import app
    import api.knowledge as knowledge_api
    from services.technician_service import TechnicianService
    from db.db_router import DatabaseRouter
    monkeypatch.setattr(app, "get_knowledge_service", lambda: knowledge)
    monkeypatch.setattr(knowledge_api, "get_knowledge_service", lambda: knowledge)
    tech_db = DatabaseRouter(f"sqlite:///{(tmp_path / 'technicians.db').as_posix()}")
    monkeypatch.setattr(TechnicianService, "__init__", lambda self: setattr(self, "db", tech_db))
    # App initialization seeds technicians, which this lightweight injected service skips.
    monkeypatch.setattr(TechnicianService, "initialize_default_technicians", lambda self: True)
    import api.chat_handler as chat
    p = processor("appointment")
    monkeypatch.setattr(chat, "task_agent", SimpleNamespace(classify_task_stream=p.process_task_stream))
    with TestClient(app.app) as client:
        yield client
    tech_db.close()


def test_knowledge_api_crud_refreshes_chat_index(client, knowledge):
    payload = {"question": "价格？", "answer": "80元", "category": "价格"}
    assert client.post("/api/knowledge/", json=payload).status_code == 200
    listing = client.get("/api/knowledge/").json()
    assert listing["total_count"] == 1
    doc_id = listing["documents"][0]["id"]
    assert knowledge.index.ntotal == 1
    payload["answer"] = "90元"
    assert client.put(f"/api/knowledge/{doc_id}", json=payload).status_code == 200
    found = client.post("/api/knowledge/search", json={"query": "价格"}).json()["data"]
    assert "90元" in found[0]["content"]
    assert client.delete(f"/api/knowledge/{doc_id}").status_code == 200
    assert knowledge.index is None
    assert client.get(f"/api/knowledge/{doc_id}").status_code == 404


@pytest.mark.parametrize("path", ["/api/appointment/create", "/api/consultation/ask", "/api/task/classify"])
def test_retired_api_is_not_registered(client, path):
    assert client.post(path, json={}).status_code == 404
    assert path not in client.get("/openapi.json").json()["paths"]


@pytest.mark.parametrize("path", ["/chat", "/chat/stream"])
def test_chat_aliases_use_shared_workflow(client, path):
    reply = client.post(path, json={"message": "预约按摩"})
    assert reply.status_code == 200
    assert "预约:预约按摩" in reply.text


def test_page_aliases_and_relative_behavior_api(client):
    first = client.get("/user_behavior")
    second = client.get("/user_behavior_analysis")
    assert first.status_code == second.status_code == 200
    assert first.text == second.text
    assert "127.0.0.1:8000" not in first.text
    assert "'/api/user-behavior/analysis'" in first.text


def test_aliases_bind_same_handler(client):
    routes = {r.path: r.endpoint for r in client.app.routes if hasattr(r, "endpoint")}
    assert routes["/chat"] is routes["/chat/stream"]
    assert routes["/api/user-behavior/analysis"] is routes["/api/user-behavior/dashboard_data"]
    assert routes["/api/user-behavior/analysis"] is routes["/api/user_behavior/dashboard_data"]
