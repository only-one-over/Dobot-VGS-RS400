#include "dobot_core/nms.h"
#include <vector>
#include <algorithm>
#include <numeric>

py::list nms(py::array_t<double> boxes, py::array_t<double> scores, double iou_threshold) {
    auto b = boxes.unchecked<2>();
    auto s = scores.unchecked<1>();

    py::ssize_t n = s.shape(0);
    if (n == 0) {
        return py::list();
    }

    std::vector<int> order(n);
    std::iota(order.begin(), order.end(), 0);
    std::stable_sort(order.begin(), order.end(), [&s](int a, int b) {
        return s(a) > s(b);
    });

    std::vector<bool> suppressed(n, false);
    py::list keep;

    for (py::ssize_t i = 0; i < n; ++i) {
        int idx = order[i];
        if (suppressed[idx]) continue;
        keep.append(idx);

        double ix1 = b(idx, 0), iy1 = b(idx, 1), ix2 = b(idx, 2), iy2 = b(idx, 3);
        double area_i = (ix2 - ix1) * (iy2 - iy1);

        for (py::ssize_t j = i + 1; j < n; ++j) {
            int jdx = order[j];
            if (suppressed[jdx]) continue;

            double xx1 = std::max(ix1, (double)b(jdx, 0));
            double yy1 = std::max(iy1, (double)b(jdx, 1));
            double xx2 = std::min(ix2, (double)b(jdx, 2));
            double yy2 = std::min(iy2, (double)b(jdx, 3));

            double w = std::max(0.0, xx2 - xx1);
            double h = std::max(0.0, yy2 - yy1);
            double inter = w * h;

            double area_j = ((double)b(jdx, 2) - (double)b(jdx, 0)) *
                            ((double)b(jdx, 3) - (double)b(jdx, 1));
            double union_area = area_i + area_j - inter;

            double iou = (union_area > 0.0) ? (inter / union_area) : 0.0;

            if (iou > iou_threshold) {
                suppressed[jdx] = true;
            }
        }
    }

    return keep;
}
