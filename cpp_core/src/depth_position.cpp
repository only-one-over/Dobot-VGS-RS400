#include "dobot_core/depth_position.h"
#include <algorithm>
#include <cmath>
#include <vector>

namespace {

bool valid_depth(double depth_meters, double min_depth, double max_depth) {
    return depth_meters > 0.0 && depth_meters >= min_depth && depth_meters <= max_depth;
}

double median_in_place(std::vector<double>& values) {
    if (values.empty()) {
        return 0.0;
    }
    const size_t mid = values.size() / 2;
    std::nth_element(values.begin(), values.begin() + mid, values.end());
    double median = values[mid];
    if (values.size() % 2 == 0) {
        std::nth_element(values.begin(), values.begin() + mid - 1, values.end());
        median = (median + values[mid - 1]) * 0.5;
    }
    return median;
}

bool parse_bbox(py::object bbox, int width, int height, int& x1, int& y1, int& x2, int& y2) {
    if (bbox.is_none()) {
        x1 = 0;
        y1 = 0;
        x2 = width;
        y2 = height;
        return false;
    }

    py::sequence seq = bbox.cast<py::sequence>();
    if (py::len(seq) < 4) {
        x1 = 0;
        y1 = 0;
        x2 = width;
        y2 = height;
        return false;
    }

    x1 = std::max(0, std::min(width - 1, seq[0].cast<int>()));
    y1 = std::max(0, std::min(height - 1, seq[1].cast<int>()));
    x2 = std::max(x1 + 1, std::min(width, seq[2].cast<int>()));
    y2 = std::max(y1 + 1, std::min(height, seq[3].cast<int>()));
    return true;
}

}  // namespace

py::object calculate_object_position(
    py::array_t<uint16_t, py::array::c_style | py::array::forcecast> depth_image,
    py::array_t<uint8_t, py::array::c_style | py::array::forcecast> mask,
    py::object bbox,
    double fx,
    double fy,
    double cx,
    double cy,
    double depth_scale,
    double min_depth,
    double max_depth
) {
    auto depth = depth_image.unchecked<2>();
    auto mask_buf = mask.unchecked<2>();

    const int height = static_cast<int>(depth.shape(0));
    const int width = static_cast<int>(depth.shape(1));

    if (height <= 0 || width <= 0 || mask_buf.shape(0) != depth.shape(0) || mask_buf.shape(1) != depth.shape(1)) {
        return py::none();
    }

    long long count = 0;
    long double sum_x = 0.0L;
    long double sum_y = 0.0L;

    for (int y = 0; y < height; ++y) {
        for (int x = 0; x < width; ++x) {
            if (mask_buf(y, x) > 127) {
                sum_x += x;
                sum_y += y;
                ++count;
            }
        }
    }

    if (count == 0) {
        return py::none();
    }

    const int center_x = static_cast<int>(sum_x / count);
    const int center_y = static_cast<int>(sum_y / count);
    const uint16_t center_depth_raw = depth(center_y, center_x);
    double depth_meters = static_cast<double>(center_depth_raw) * depth_scale;

    if (!valid_depth(depth_meters, min_depth, max_depth)) {
        int x1 = 0;
        int y1 = 0;
        int x2 = width;
        int y2 = height;
        parse_bbox(bbox, width, height, x1, y1, x2, y2);

        std::vector<double> valid_depths;
        valid_depths.reserve(static_cast<size_t>((x2 - x1) * (y2 - y1)));

        for (int y = y1; y < y2; ++y) {
            for (int x = x1; x < x2; ++x) {
                if (mask_buf(y, x) <= 127) {
                    continue;
                }
                const double value = static_cast<double>(depth(y, x)) * depth_scale;
                if (valid_depth(value, min_depth, max_depth)) {
                    valid_depths.push_back(value);
                }
            }
        }

        if (valid_depths.empty()) {
            return py::none();
        }
        depth_meters = median_in_place(valid_depths);
    }

    if (!valid_depth(depth_meters, min_depth, max_depth) || fx == 0.0 || fy == 0.0) {
        return py::none();
    }

    const double z_mm = depth_meters * 1000.0;
    const double x_mm = (static_cast<double>(center_x) - cx) * z_mm / fx;
    const double y_mm = (static_cast<double>(center_y) - cy) * z_mm / fy;

    py::dict result;
    result["center_x"] = center_x;
    result["center_y"] = center_y;
    result["depth"] = depth_meters;
    result["camera_coords"] = py::make_tuple(x_mm, y_mm, z_mm);
    return result;
}
