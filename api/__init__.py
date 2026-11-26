"""Active management API routers; chat is served by web.routes."""
from .knowledge import router as knowledge_router
from .technician import router as technician_router
from .user_behavior_analysis import router as user_behavior_router, router_underscore

api_routers = [knowledge_router, technician_router, user_behavior_router, router_underscore]
