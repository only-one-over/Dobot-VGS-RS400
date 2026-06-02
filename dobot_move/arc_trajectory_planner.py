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
            waypoints.append([x, y, z, self.orientation[0], self.orientation[1], self.orientation[2]])
        return waypoints

    def generate_arc_by_three_points(self, p1, p2, p3):
        ax = p2[0] - p1[0]
        ay = p2[1] - p1[1]
        az = p2[2] - p1[2]
        bx = p3[0] - p1[0]
        by = p3[1] - p1[1]
        bz = p3[2] - p1[2]

        nx = ay * bz - az * by
        ny = az * bx - ax * bz
        nz = ax * by - ay * bx

        n_len_sq = nx * nx + ny * ny + nz * nz
        if abs(n_len_sq) < 1e-10:
            raise ValueError

        a_len_sq = ax * ax + ay * ay + az * az
        b_len_sq = bx * bx + by * by + bz * bz

        bxn_x = by * nz - bz * ny
        bxn_y = bz * nx - bx * nz
        bxn_z = bx * ny - by * nx

        nxa_x = ny * az - nz * ay
        nxa_y = nz * ax - nx * az
        nxa_z = nx * ay - ny * ax

        d = 2 * n_len_sq

        center_x = p1[0] + (a_len_sq * bxn_x + b_len_sq * nxa_x) / d
        center_y = p1[1] + (a_len_sq * bxn_y + b_len_sq * nxa_y) / d
        center_z = p1[2] + (a_len_sq * bxn_z + b_len_sq * nxa_z) / d

        radius = math.sqrt((center_x - p1[0]) ** 2 + (center_y - p1[1]) ** 2 + (center_z - p1[2]) ** 2)

        abs_nx, abs_ny, abs_nz = abs(nx), abs(ny), abs(nz)
        if abs_nx >= abs_ny and abs_nx >= abs_nz:
            rotation_axis = 'X'
        elif abs_ny >= abs_nx and abs_ny >= abs_nz:
            rotation_axis = 'Y'
        else:
            rotation_axis = 'Z'

        if rotation_axis == 'Z':
            start_angle = math.degrees(math.atan2(p1[1] - center_y, p1[0] - center_x))
            end_angle = math.degrees(math.atan2(p3[1] - center_y, p3[0] - center_x))
        elif rotation_axis == 'Y':
            start_angle = math.degrees(math.atan2(p1[2] - center_z, p1[0] - center_x))
            end_angle = math.degrees(math.atan2(p3[2] - center_z, p3[0] - center_x))
        elif rotation_axis == 'X':
            start_angle = math.degrees(math.atan2(p1[2] - center_z, p1[1] - center_y))
            end_angle = math.degrees(math.atan2(p3[2] - center_z, p3[1] - center_y))

        self.center = [center_x, center_y, center_z]
        self.radius = radius
        self.start_angle = start_angle
        self.end_angle = end_angle
        self.rotation_axis = rotation_axis

        return self.generate_waypoints()

    def get_arc_info(self):
        arc_length = self.radius * abs(self.end_angle - self.start_angle) * math.pi / 180
        return {
            'center': self.center,
            'radius': self.radius,
            'start_angle': self.start_angle,
            'end_angle': self.end_angle,
            'arc_length': arc_length
        }
