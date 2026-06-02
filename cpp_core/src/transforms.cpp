#define _USE_MATH_DEFINES
#include "dobot_core/transforms.h"
#include <cmath>
#include <vector>

py::array_t<double> euler2rot(double rx, double ry, double rz, bool degree) {
    if (degree) {
        rx = rx * M_PI / 180.0;
        ry = ry * M_PI / 180.0;
        rz = rz * M_PI / 180.0;
    }

    double cx = std::cos(rx), sx = std::sin(rx);
    double cy = std::cos(ry), sy = std::sin(ry);
    double cz = std::cos(rz), sz = std::sin(rz);

    double Rx[3][3] = {
        {1.0, 0.0, 0.0},
        {0.0, cx, -sx},
        {0.0, sx, cx}
    };

    double Ry[3][3] = {
        {cy, 0.0, sy},
        {0.0, 1.0, 0.0},
        {-sy, 0.0, cy}
    };

    double Rz[3][3] = {
        {cz, -sz, 0.0},
        {sz, cz, 0.0},
        {0.0, 0.0, 1.0}
    };

    double RyRx[3][3] = {};
    for (int i = 0; i < 3; ++i)
        for (int j = 0; j < 3; ++j)
            for (int k = 0; k < 3; ++k)
                RyRx[i][j] += Ry[i][k] * Rx[k][j];

    auto result = py::array_t<double>({3, 3});
    auto buf = result.mutable_unchecked<2>();

    for (int i = 0; i < 3; ++i)
        for (int j = 0; j < 3; ++j) {
            double val = 0.0;
            for (int k = 0; k < 3; ++k)
                val += Rz[i][k] * RyRx[k][j];
            buf(i, j) = val;
        }

    return result;
}

py::array_t<double> pose2matrix(double x, double y, double z, double rx, double ry, double rz) {
    py::array_t<double> R_arr = euler2rot(rx, ry, rz, true);
    auto R = R_arr.unchecked<2>();

    auto result = py::array_t<double>({4, 4});
    auto buf = result.mutable_unchecked<2>();

    for (int i = 0; i < 4; ++i)
        for (int j = 0; j < 4; ++j)
            buf(i, j) = 0.0;

    for (int i = 0; i < 3; ++i)
        for (int j = 0; j < 3; ++j)
            buf(i, j) = R(i, j);

    buf(0, 3) = x;
    buf(1, 3) = y;
    buf(2, 3) = z;
    buf(3, 3) = 1.0;

    return result;
}

py::array_t<double> transform_point(py::array_t<double> matrix, py::array_t<double> point) {
    auto m = matrix.unchecked<2>();
    auto p = point.unchecked<1>();

    double px = p(0), py_val = p(1), pz = p(2);

    auto result = py::array_t<double>(3);
    auto buf = result.mutable_unchecked<1>();

    buf(0) = m(0, 0) * px + m(0, 1) * py_val + m(0, 2) * pz + m(0, 3);
    buf(1) = m(1, 0) * px + m(1, 1) * py_val + m(1, 2) * pz + m(1, 3);
    buf(2) = m(2, 0) * px + m(2, 1) * py_val + m(2, 2) * pz + m(2, 3);

    return result;
}
