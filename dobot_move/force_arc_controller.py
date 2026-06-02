import logging
import math
from dobot_api import DobotApiDashboard, DobotApiFeedBack
from arc_trajectory_planner import ArcTrajectoryPlanner
from force_feedback_monitor import ForceFeedbackMonitor

logger = logging.getLogger(__name__)


class ForceArcController:

    def __init__(self, ip=None, dashboard_port=29999, feed_port=30004):
        self.ip = ip
        self.dashboard_port = dashboard_port
        self.feed_port = feed_port
        self.dashboard = None
        self.feed = None
        self._external_dashboard = False
        self.monitor = None
        self.planner = None
        self.waypoints = []
        self.speed_factor = 20
        self.fc_config = {}

    def set_dashboard(self, dashboard):
        self.dashboard = dashboard
        self._external_dashboard = True

    def connect(self):
        self.dashboard = DobotApiDashboard(self.ip, self.dashboard_port)
        self.feed = DobotApiFeedBack(self.ip, self.feed_port)
        result = self.dashboard.EnableRobot()
        return result

    def disconnect(self):
        if self.monitor is not None and self.monitor.is_running():
            self.monitor.stop()
        if not self._external_dashboard:
            if self.dashboard is not None:
                self.dashboard.close()
            if self.feed is not None:
                self.feed.close()

    def configure_force_control(self, deviation_pos=100, deviation_rot=36, controltype=1,
                                force_limit=None, damping=None, stiffness=None, mass=None, speed_limit=None):
        if force_limit is None:
            force_limit = {'x': 200, 'y': 200, 'z': 200, 'rx': 12, 'ry': 12, 'rz': 12}
        if damping is None:
            damping = {'x': 50, 'y': 50, 'z': 50, 'rx': 5, 'ry': 5, 'rz': 5}
        if stiffness is None:
            stiffness = {'x': 0, 'y': 0, 'z': 0, 'rx': 0, 'ry': 0, 'rz': 0}
        if mass is None:
            mass = {'x': 0, 'y': 0, 'z': 0, 'rx': 0, 'ry': 0, 'rz': 0}
        if speed_limit is None:
            speed_limit = {'x': 500, 'y': 500, 'z': 500, 'rx': 30, 'ry': 30, 'rz': 30}
        self.fc_config = {
            'deviation_pos': deviation_pos,
            'deviation_rot': deviation_rot,
            'controltype': controltype,
            'force_limit': force_limit,
            'damping': damping,
            'stiffness': stiffness,
            'mass': mass,
            'speed_limit': speed_limit,
        }

    def configure_arc(self, center, radius, start_angle, end_angle, rotation_axis='Z',
                      num_waypoints=50, orientation=None, speed_factor=20):
        self.planner = ArcTrajectoryPlanner(
            center=center, radius=radius, start_angle=start_angle, end_angle=end_angle,
            rotation_axis=rotation_axis, num_waypoints=num_waypoints, orientation=orientation
        )
        self.waypoints = self.planner.generate_waypoints()
        self.speed_factor = speed_factor

    def execute(self, fc_axes=None, target_force=None, correction_gain=0.3, monitor_freq=10):
        if fc_axes is None:
            fc_axes = {'x': 0, 'y': 0, 'z': 0, 'rx': 1, 'ry': 1, 'rz': 1}
        if target_force is None:
            target_force = {'fx': 0, 'fy': 0, 'fz': 0, 'frx': 0, 'fry': 0, 'frz': 0}
        fc = self.fc_config
        try:
            self.dashboard.EnableFTSensor(1)
            self.dashboard.SixForceHome()
            self.dashboard.SpeedFactor(self.speed_factor)
            self.dashboard.FCSetDeviation(
                fc['deviation_pos'], fc['deviation_pos'], fc['deviation_pos'],
                fc['deviation_rot'], fc['deviation_rot'], fc['deviation_rot'],
                controltype=fc['controltype']
            )
            fl = fc['force_limit']
            self.dashboard.FCSetForceLimit(fl['x'], fl['y'], fl['z'], fl['rx'], fl['ry'], fl['rz'])
            dp = fc['damping']
            self.dashboard.FCSetDamping(dp['x'], dp['y'], dp['z'], dp['rx'], dp['ry'], dp['rz'])
            st = fc['stiffness']
            self.dashboard.FCSetStiffness(st['x'], st['y'], st['z'], st['rx'], st['ry'], st['rz'])
            ms = fc['mass']
            self.dashboard.FCSetMass(ms['x'], ms['y'], ms['z'], ms['rx'], ms['ry'], ms['rz'])
            sl = fc['speed_limit']
            self.dashboard.FCSetForceSpeedLimit(sl['x'], sl['y'], sl['z'], sl['rx'], sl['ry'], sl['rz'])
            self.dashboard.FCForceMode(
                fc_axes['x'], fc_axes['y'], fc_axes['z'],
                fc_axes['rx'], fc_axes['ry'], fc_axes['rz'],
                target_force['fx'], target_force['fy'], target_force['fz'],
                target_force['frx'], target_force['fry'], target_force['frz']
            )
            self.monitor = ForceFeedbackMonitor(self.dashboard, monitor_freq=monitor_freq)
            self.monitor.start()
            total = len(self.waypoints)
            for i, wp in enumerate(self.waypoints):
                self.dashboard.MovJ(wp[0], wp[1], wp[2], wp[3], wp[4], wp[5], coordinateMode=0)
                deviation = self.monitor.get_force_deviation(target_force)
                correction = self.monitor.get_correction(target_force, gain=correction_gain)
                has_correction = any(abs(v) > 1e-6 for v in correction.values())
                if has_correction:
                    self.dashboard.FCSetForce(
                        correction['fx'], correction['fy'], correction['fz'],
                        correction['frx'], correction['fry'], correction['frz']
                    )
                logger.debug(f"Waypoint {i + 1}/{total}: pos=[{wp[0]:.2f},{wp[1]:.2f},{wp[2]:.2f}] "
                      f"deviation={deviation} correction={'applied' if has_correction else 'none'}")
        finally:
            try:
                self.dashboard.FCOff()
            except Exception:
                pass
            if self.monitor is not None:
                self.monitor.stop()

    def execute_with_three_points(self, p1, p2, p3, **kwargs):
        self.planner = ArcTrajectoryPlanner(
            center=[0, 0, 0], radius=1, start_angle=0, end_angle=1
        )
        self.waypoints = self.planner.generate_arc_by_three_points(p1, p2, p3)
        return self.execute(**kwargs)
