"""
用户行为服务层

职责：
1. 封装用户行为相关的数据库操作
2. 处理用户行为分析业务逻辑
3. 提供用户偏好管理服务
"""

from typing import Dict, Any, List
from db.db_router import DatabaseRouter
import logging

logger = logging.getLogger(__name__)

class UserBehaviorService:
    """用户行为服务类"""
    
    def __init__(self, db_path: str = 'sqlite:///data/smart_appointment.db'):
        self.db_router = DatabaseRouter(db_path)
        self.user_behavior_repo = self.db_router.user_behavior
    
    def record_behavior(self, user_id: str, action_type: str, action_data: Dict[str, Any] = None,
                       technician_id: str = None, session_id: str = "default_session") -> bool:
        """记录用户行为"""
        try:
            behavior_id = self.user_behavior_repo.record_behavior(
                user_id=user_id,
                action_type=action_type,
                action_data=action_data,
                technician_id=technician_id,
                session_id=session_id
            )
            
            if behavior_id:
                logger.info(f"用户行为记录成功：用户={user_id}, 行为={action_type}, ID={behavior_id}")
                return True
            return False
            
        except Exception as e:
            logger.error(f"记录用户行为失败：{e}")
            return False
    
    def get_user_behaviors(self, user_id: str, action_type: str = None, 
                          days_back: int = None) -> List[Dict[str, Any]]:
        """获取用户行为记录"""
        try:
            return self.user_behavior_repo.get_user_behaviors(user_id, action_type, days_back)
        except Exception as e:
            logger.error(f"获取用户行为记录失败：{e}")
            return []
