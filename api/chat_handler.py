from agents.task_classification_agent import TaskClassificationAgent
from agents.appointment_agent import AppointmentAgent
from agents.consultant_agent import ConsultantAgent
import uuid

# 全局session_id用于单用户场景
global_session_id = str(uuid.uuid4())

task_agent = TaskClassificationAgent(
    AppointmentAgent(session_id=global_session_id), 
    ConsultantAgent(session_id=global_session_id)
)

async def ProcessUserInput_stream(user_input):
    """Forward a user message to the shared chat dispatcher."""
    async for token in task_agent.classify_task_stream(user_input):
        yield token
