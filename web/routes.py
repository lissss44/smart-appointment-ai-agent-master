"""
Web界面路由

处理前端页面渲染和聊天功能
"""
from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse, StreamingResponse
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel
from api.chat_handler import ProcessUserInput_stream
import logging

# 创建logger实例
logger = logging.getLogger(__name__)
# 模板配置
templates = Jinja2Templates(directory="web/templates")

# Web路由器
router = APIRouter(tags=["Web界面"])

class ChatRequest(BaseModel):
    message: str


@router.get("/", response_class=HTMLResponse, summary="主页")
async def read_root(request: Request):
    """渲染主页聊天界面"""
    return templates.TemplateResponse("index.html", {"request": request})


@router.post("/chat/stream", summary="流式聊天")
async def chat_stream_endpoint(chat: ChatRequest):
    """处理流式聊天请求"""
    async def token_generator():
        async for token in ProcessUserInput_stream(chat.message):
            yield token
    ##使用这个数据响应流式数据给前端，前端会逐步接收数据并显示
    return StreamingResponse(token_generator(), media_type="text/plain")


@router.get("/user_behavior", response_class=HTMLResponse, summary="用户行为分析页面")
async def user_behavior_page(request: Request):
    """用户行为分析页面"""
    return templates.TemplateResponse("user_behavior_analysis.html", {"request": request})

@router.get("/knowledge", response_class=HTMLResponse, summary="知识库管理页面")
async def knowledge_page(request: Request):
    """返回页面；知识列表由前端调用 /api/knowledge 加载。"""
    return templates.TemplateResponse("knowledge_management.html", {"request": request})

@router.get("/technician", response_class=HTMLResponse, summary="技师状态页面")
async def technician_page(request: Request):
    """技师状态页面"""
    # 通过API层获取技师数据
    try:
        from api.technician import get_all_technicians
        
        # 调用API层函数获取数据
        technicians = await get_all_technicians()
        
        return templates.TemplateResponse("technician.html", {
            "request": request,
            "technicians": technicians
        })
    except Exception as e:
        return templates.TemplateResponse("technician.html", {
            "request": request,
            "technicians": [],
            "error": str(e)
        })

@router.get("/technician_schedule", response_class=HTMLResponse, summary="技师排班页面")
async def technician_schedule_page(request: Request):
    """技师排班页面"""
    try:
        from api.technician import get_all_technicians_schedule_today
        from config.time_config import time_config
        
        # 获取当前日期
        current_date = time_config.current_date_str()
        
        # 通过API层获取所有技师的排班数据
        schedules_data = await get_all_technicians_schedule_today()
        
        # 构建排班数据格式 - 直接使用API返回的数据
        schedule = []
        for schedule_item in schedules_data:
            schedule.append({
                "id": schedule_item["technician_id"],
                "name": schedule_item["technician_name"],
                "busy_periods": schedule_item["busy_periods"]
            })
        
        return templates.TemplateResponse("technician_schedule.html", {
            "request": request,
            "schedule": schedule,
            "current_date": current_date
        })
    except Exception as e:
        logger.error(f"加载技师排班数据失败: {str(e)}")
        return templates.TemplateResponse("technician_schedule.html", {
            "request": request,
            "schedule": [],
            "error": str(e)
        })
