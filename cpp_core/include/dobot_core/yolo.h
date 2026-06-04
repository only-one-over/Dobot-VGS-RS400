#pragma once
#include <pybind11/pybind11.h>
#include <pybind11/numpy.h>
namespace py = pybind11;

py::list postprocess_yolov8(py::list outputs, py::tuple original_size, double scale,
                            py::tuple offset, py::tuple new_size, int num_classes,
                            double conf_threshold = 0.25, double iou_threshold = 0.5);
py::list postprocess_yolo26(
    py::list outputs,
    py::tuple original_size,
    double scale,
    py::tuple offset,
    py::tuple new_size,
    int num_classes,
    float conf_threshold = 0.25
);
py::list process_mask(py::array_t<float> protos, py::array_t<float> masks_in,
                      py::array_t<double> bboxes, py::tuple shape, double scale,
                      py::tuple offset, py::tuple new_size, double threshold = 0.5);
