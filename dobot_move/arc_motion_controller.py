import logging
import re

from arc_trajectory_planner import ArcTrajectoryPlanner
from dobot_api import DobotApiDashboard

logger = logging.getLogger(__name__)


class ArcMotionController:
    """Generate and execute a native Dobot Arc motion."""

    def __init__(self, ip=None, dashboard_port=29999, user_index=0, tool_index=0):
        self.ip = ip
        self.dashboard_port = dashboard_port
        self.dashboard = None
        self._external_dashboard = False
        self.planner = None
        self.waypoints = []
        self.speed_factor = 20
        self._user_index = user_index
        self._tool_index = tool_index

    def set_dashboard(self, dashboard):
        self.dashboard = dashboard
        self._external_dashboard = True

    def connect(self):
        self.dashboard = DobotApiDashboard(self.ip, self.dashboard_port)
        result = self.dashboard.EnableRobot()
        return result

    def disconnect(self):
        if not self._external_dashboard and self.dashboard is not None:
            self.dashboard.close()

    def configure_arc(self, center, radius, start_angle, end_angle, rotation_axis='Z',
                      num_waypoints=3, orientation=None, speed_factor=20):
        # Dobot Arc needs current pose + one middle pose + one end pose.
        num_waypoints = 3
        self.planner = ArcTrajectoryPlanner(
            center=center,
            radius=radius,
            start_angle=start_angle,
            end_angle=end_angle,
            rotation_axis=rotation_axis,
            num_waypoints=num_waypoints,
            orientation=orientation,
        )
        self.waypoints = self.planner.generate_waypoints()
        self.speed_factor = speed_factor
        if self.waypoints:
            logger.info(
                "arc trajectory: center=%s radius=%.2f angle=%.2f->%.2f axis=%s waypoints=%d first=%s mid=%s last=%s",
                [round(float(v), 3) for v in center],
                float(radius),
                float(start_angle),
                float(end_angle),
                rotation_axis,
                len(self.waypoints),
                [round(float(v), 3) for v in self.waypoints[0]],
                [round(float(v), 3) for v in self.waypoints[len(self.waypoints) // 2]],
                [round(float(v), 3) for v in self.waypoints[-1]],
            )

    @staticmethod
    def _parse_response_code(response):
        if response is None:
            return None
        match = re.search(r'-?\d+', str(response))
        return int(match.group(0)) if match else None

    def _check_response(self, name, response):
        code = self._parse_response_code(response)
        logger.debug("%s response: %s", name, response)
        if code != 0:
            raise RuntimeError(f"{name} failed, response={response}, code={code}")
        return response

    @staticmethod
    def _i(value):
        return int(round(float(value)))

    def execute(self, set_speed=True):
        if self.dashboard is None:
            raise RuntimeError("ArcMotionController dashboard is not configured")
        if not self.waypoints:
            raise RuntimeError("Arc motion waypoints are empty")
        if set_speed:
            self._check_response("SpeedFactor", self.dashboard.SpeedFactor(self._i(self.speed_factor)))
        mid = self.waypoints[len(self.waypoints) // 2]
        end = self.waypoints[-1]
        resp = self.dashboard.Arc(
            mid[0], mid[1], mid[2], mid[3], mid[4], mid[5],
            end[0], end[1], end[2], end[3], end[4], end[5],
            coordinateMode=0,
            user=self._i(self._user_index),
            tool=self._i(self._tool_index),
            v=self._i(self.speed_factor),
        )
        command_id = None
        resp_str = str(resp)
        ids = [int(n) for n in re.findall(r"-?\d+", resp_str)]
        code = ids[0] if ids else -1
        if code != 0:
            raise RuntimeError(f"Arc failed, response={resp_str}, code={code}")
        if len(ids) > 1:
            command_id = ids[1]
        logger.debug(
            "Arc command: mid=[%.2f, %.2f, %.2f, %.2f, %.2f, %.2f] "
            "end=[%.2f, %.2f, %.2f, %.2f, %.2f, %.2f] command_id=%s",
            mid[0], mid[1], mid[2], mid[3], mid[4], mid[5],
            end[0], end[1], end[2], end[3], end[4], end[5],
            command_id,
        )
        return command_id
