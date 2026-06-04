#pragma once
#include <pybind11/pybind11.h>
#include <pybind11/numpy.h>

namespace py = pybind11;

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
);
