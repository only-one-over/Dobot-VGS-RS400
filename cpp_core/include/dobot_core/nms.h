#pragma once
#include <pybind11/pybind11.h>
#include <pybind11/numpy.h>
namespace py = pybind11;

py::list nms(py::array_t<double> boxes, py::array_t<double> scores, double iou_threshold = 0.5);
