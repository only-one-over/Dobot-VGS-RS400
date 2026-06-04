#include <pybind11/pybind11.h>
#include "dobot_core/transforms.h"
#include "dobot_core/nms.h"
#include "dobot_core/yolo.h"
#include "dobot_core/depth_position.h"

namespace py = pybind11;

PYBIND11_MODULE(dobot_core, m) {
    m.doc() = "Dobot core C++ acceleration module";

    auto transforms = m.def_submodule("transforms", "Coordinate transformation functions");
    transforms.def("euler2rot", &euler2rot, "Convert Euler angles to rotation matrix",
                   py::arg("rx"), py::arg("ry"), py::arg("rz"), py::arg("degree") = true);
    transforms.def("pose2matrix", &pose2matrix, "Convert pose to homogeneous matrix",
                   py::arg("x"), py::arg("y"), py::arg("z"), py::arg("rx"), py::arg("ry"), py::arg("rz"));
    transforms.def("transform_point", &transform_point, "Transform point using homogeneous matrix",
                   py::arg("matrix"), py::arg("point"));

    auto nms_mod = m.def_submodule("nms", "Non-Maximum Suppression");
    nms_mod.def("nms", &nms, "Perform NMS on bounding boxes",
                py::arg("boxes"), py::arg("scores"), py::arg("iou_threshold") = 0.5);

    auto yolo_mod = m.def_submodule("yolo", "YOLOv8 post-processing");
    yolo_mod.def("postprocess_yolov8", &postprocess_yolov8, "Post-process YOLOv8 model outputs",
                 py::arg("outputs"), py::arg("original_size"), py::arg("scale"),
                 py::arg("offset"), py::arg("new_size"), py::arg("num_classes"),
                 py::arg("conf_threshold") = 0.25, py::arg("iou_threshold") = 0.5);
    yolo_mod.def("postprocess_yolo26", &postprocess_yolo26,
                 "Post-process YOLO26 end-to-end detection output",
                 py::arg("outputs"),
                 py::arg("original_size"),
                 py::arg("scale"),
                 py::arg("offset"),
                 py::arg("new_size"),
                 py::arg("num_classes"),
                 py::arg("conf_threshold") = 0.25f);
    yolo_mod.def("process_mask", &process_mask, "Generate masks from prototypes and coefficients",
                 py::arg("protos"), py::arg("masks_in"), py::arg("bboxes"), py::arg("shape"),
                 py::arg("scale"), py::arg("offset"), py::arg("new_size"), py::arg("threshold") = 0.5);

    auto depth_mod = m.def_submodule("depth", "Depth image position functions");
    depth_mod.def("calculate_object_position", &calculate_object_position,
                  "Calculate camera-space object position from depth and segmentation mask",
                  py::arg("depth_image"), py::arg("mask"), py::arg("bbox"),
                  py::arg("fx"), py::arg("fy"), py::arg("cx"), py::arg("cy"),
                  py::arg("depth_scale"), py::arg("min_depth"), py::arg("max_depth"));
}
