#pragma once
#include <pybind11/pybind11.h>
#include <pybind11/numpy.h>
namespace py = pybind11;

py::array_t<double> euler2rot(double rx, double ry, double rz, bool degree = true);
py::array_t<double> pose2matrix(double x, double y, double z, double rx, double ry, double rz);
py::array_t<double> transform_point(py::array_t<double> matrix, py::array_t<double> point);
