import logging

logger = logging.getLogger(__name__)

try:
    from .robot_controller import DobotController
except Exception as e:
    logger.warning("DobotController 导入失败: %s", e)
    DobotController = None

try:
    from .modbus_server import DobotModbusServer
except Exception as e:
    logger.warning("DobotModbusServer 导入失败: %s", e)
    DobotModbusServer = None

try:
    from .vision_system import VisionSystem
except Exception as e:
    logger.warning("VisionSystem 导入失败，视觉功能不可用: %s", e)
    VisionSystem = None

__all__ = [
    "DobotController",
    "VisionSystem",
    "DobotModbusServer",
]
