import math


class ArcTrajectoryPlanner:
    def __init__(self, center, radius, start_angle, end_angle, rotation_axis='Z', num_waypoints=50, orientation=None):
        if radius <= 0:
            raise ValueError
        if start_angle == end_angle:
            raise ValueError
        self.center = center
        self.radius = radius
        self.start_angle = start_angle
        self.end_angle = end_angle
        self.rotation_axis = rotation_axis
        self.num_waypoints = num_waypoints
        self.orientation = orientation if orientation is not None else [0, 0, 0]

    def generate_waypoints(self):
        waypoints = []
        cx, cy, cz = self.center
        for i in range(self.num_waypoints):
            if self.num_waypoints > 1:
                theta = math.radians(self.start_angle + (self.end_angle - self.start_angle) * i / (self.num_waypoints - 1))
            else:
                theta = math.radians(self.start_angle)
            if self.rotation_axis == 'Z':
                x = cx + self.radius * math.cos(theta)
                y = cy + self.radius * math.sin(theta)
                z = cz
            elif self.rotation_axis == 'Y':
                x = cx + self.radius * math.cos(theta)
                z = cz + self.radius * math.sin(theta)
                y = cy
            elif self.rotation_axis == 'X':
                y = cy + self.radius * math.cos(theta)
                z = cz + self.radius * math.sin(theta)
                x = cx
            if self.orientation and len(self.orientation) == self.num_waypoints and isinstance(self.orientation[0], (list, tuple)):
                orientation = self.orientation[i]
            else:
                orientation = self.orientation
            waypoints.append([x, y, z, orientation[0], orientation[1], orientation[2]])
        return waypoints

    def get_arc_info(self):
        arc_length = self.radius * abs(self.end_angle - self.start_angle) * math.pi / 180
        return {
            'center': self.center,
            'radius': self.radius,
            'start_angle': self.start_angle,
            'end_angle': self.end_angle,
            'arc_length': arc_length
        }
