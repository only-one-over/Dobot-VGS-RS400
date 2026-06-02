#include "dobot_core/yolo.h"
#include "dobot_core/nms.h"
#include <cmath>
#include <vector>
#include <algorithm>

static std::vector<float> bilinear_resize(const float* data, int src_h, int src_w, int dst_h, int dst_w) {
    std::vector<float> out(dst_h * dst_w);
    for (int y = 0; y < dst_h; ++y) {
        for (int x = 0; x < dst_w; ++x) {
            float src_x = ((float)x + 0.5f) * ((float)src_w / (float)dst_w) - 0.5f;
            float src_y = ((float)y + 0.5f) * ((float)src_h / (float)dst_h) - 0.5f;

            int x0 = (int)std::floor(src_x);
            int y0 = (int)std::floor(src_y);
            int x1 = x0 + 1;
            int y1 = y0 + 1;

            float fx = src_x - (float)x0;
            float fy = src_y - (float)y0;

            auto clamp = [](int v, int lo, int hi) -> int { return std::max(lo, std::min(hi, v)); };
            x0 = clamp(x0, 0, src_w - 1);
            x1 = clamp(x1, 0, src_w - 1);
            y0 = clamp(y0, 0, src_h - 1);
            y1 = clamp(y1, 0, src_h - 1);

            float v00 = data[y0 * src_w + x0];
            float v01 = data[y0 * src_w + x1];
            float v10 = data[y1 * src_w + x0];
            float v11 = data[y1 * src_w + x1];

            float val = v00 * (1.0f - fx) * (1.0f - fy) +
                        v01 * fx * (1.0f - fy) +
                        v10 * (1.0f - fx) * fy +
                        v11 * fx * fy;
            out[y * dst_w + x] = val;
        }
    }
    return out;
}

py::list process_mask(py::array_t<float> protos, py::array_t<float> masks_in,
                      py::array_t<double> bboxes, py::tuple shape, double scale,
                      py::tuple offset, py::tuple new_size, double threshold) {
    auto p = protos.unchecked<3>();
    auto mi = masks_in.unchecked<2>();
    auto bb = bboxes.unchecked<2>();

    int c = (int)p.shape(0), mh = (int)p.shape(1), mw = (int)p.shape(2);
    int n = (int)mi.shape(0);
    int mask_dim = (int)mi.shape(1);

    int orig_h = shape[0].cast<int>();
    int orig_w = shape[1].cast<int>();

    int x_offset_mask = offset[0].cast<int>();
    int y_offset_mask = offset[1].cast<int>();
    int new_w = new_size[0].cast<int>();
    int new_h = new_size[1].cast<int>();

    std::vector<float> protos_flat(c * mh * mw);
    for (int ci = 0; ci < c; ++ci)
        for (int yi = 0; yi < mh; ++yi)
            for (int xi = 0; xi < mw; ++xi)
                protos_flat[ci * mh * mw + yi * mw + xi] = p(ci, yi, xi);

    std::vector<float> masks_raw(n * mh * mw);
    for (int i = 0; i < n; ++i) {
        for (int j = 0; j < mh * mw; ++j) {
            float val = 0.0f;
            for (int ci = 0; ci < c && ci < mask_dim; ++ci) {
                val += mi(i, ci) * protos_flat[ci * mh * mw + j];
            }
            masks_raw[i * mh * mw + j] = 1.0f / (1.0f + std::exp(-val));
        }
    }

    py::list masks_resized;

    for (int i = 0; i < n; ++i) {
        int x1 = (int)bb(i, 0), y1 = (int)bb(i, 1), x2 = (int)bb(i, 2), y2 = (int)bb(i, 3);

        std::vector<float> mask_640 = bilinear_resize(&masks_raw[i * mh * mw], mh, mw, 640, 640);

        int crop_h = std::min(y_offset_mask + new_h, 640) - y_offset_mask;
        int crop_w = std::min(x_offset_mask + new_w, 640) - x_offset_mask;

        if (crop_h <= 0 || crop_w <= 0) {
            auto empty_mask = py::array_t<uint8_t>(orig_h * orig_w);
            auto empty_buf = empty_mask.mutable_unchecked<1>();
            for (int j = 0; j < orig_h * orig_w; ++j) empty_buf(j) = 0;
            empty_mask.resize({orig_h, orig_w});
            masks_resized.append(empty_mask);
            continue;
        }

        std::vector<float> mask_cropped(crop_h * crop_w);
        for (int cy = 0; cy < crop_h; ++cy)
            for (int cx = 0; cx < crop_w; ++cx)
                mask_cropped[cy * crop_w + cx] = mask_640[(y_offset_mask + cy) * 640 + (x_offset_mask + cx)];

        std::vector<float> mask_orig = bilinear_resize(mask_cropped.data(), crop_h, crop_w, orig_h, orig_w);

        int x1_clipped = std::max(0, std::min(orig_w, x1));
        int y1_clipped = std::max(0, std::min(orig_h, y1));
        int x2_clipped = std::max(0, std::min(orig_w, x2));
        int y2_clipped = std::max(0, std::min(orig_h, y2));

        auto full_mask = py::array_t<uint8_t>(orig_h * orig_w);
        auto fbuf = full_mask.mutable_unchecked<1>();
        for (int j = 0; j < orig_h * orig_w; ++j) fbuf(j) = 0;

        if (x2_clipped > x1_clipped && y2_clipped > y1_clipped) {
            int h_region = y2_clipped - y1_clipped;
            int w_region = x2_clipped - x1_clipped;

            std::vector<float> binary_region(h_region * w_region);
            for (int ry = 0; ry < h_region; ++ry)
                for (int rx = 0; rx < w_region; ++rx) {
                    float val = mask_orig[(y1_clipped + ry) * orig_w + (x1_clipped + rx)];
                    binary_region[ry * w_region + rx] = (val > threshold) ? 255.0f : 0.0f;
                }

            std::vector<float> mask_resized = bilinear_resize(binary_region.data(), h_region, w_region, h_region, w_region);

            for (int ry = 0; ry < h_region; ++ry)
                for (int rx = 0; rx < w_region; ++rx)
                    fbuf((y1_clipped + ry) * orig_w + (x1_clipped + rx)) = (uint8_t)mask_resized[ry * w_region + rx];
        }

        full_mask.resize({orig_h, orig_w});
        masks_resized.append(full_mask);
    }

    return masks_resized;
}

py::list postprocess_yolov8(py::list outputs, py::tuple original_size, double scale,
                            py::tuple offset, py::tuple new_size, int num_classes,
                            double conf_threshold, double iou_threshold) {
    py::list detections;

    int orig_w = original_size[0].cast<int>();
    int orig_h = original_size[1].cast<int>();

    bool is_seg_model = (py::len(outputs) >= 2);

    py::object proto_obj = py::none();
    if (is_seg_model) {
        proto_obj = outputs[1];
    }

    auto dets_raw = outputs[0].cast<py::array_t<float>>();
    py::array_t<float> dets_obj;
    if (dets_raw.ndim() == 3) {
        auto squeezed = dets_raw.reshape({dets_raw.shape(1), dets_raw.shape(2)});
        dets_obj = py::array_t<float>::ensure(squeezed.attr("T"));
    } else {
        dets_obj = dets_raw;
    }
    auto dets = dets_obj.unchecked<2>();

    py::ssize_t rows = dets.shape(0);
    py::ssize_t cols = dets.shape(1);

    std::vector<std::vector<double>> all_boxes;
    std::vector<double> all_scores;
    std::vector<std::vector<float>> all_masks_coeff;

    int x_offset = offset[0].cast<int>();
    int y_offset = offset[1].cast<int>();

    for (py::ssize_t i = 0; i < rows; ++i) {
        float cx = dets(i, 0);
        float cy = dets(i, 1);
        float w = dets(i, 2);
        float h = dets(i, 3);

        float max_score = -1.0f;
        int class_id = 0;
        for (int c = 0; c < num_classes; ++c) {
            float s = dets(i, 4 + c);
            if (s > max_score) {
                max_score = s;
                class_id = c;
            }
        }

        if (max_score <= (float)conf_threshold) continue;

        double cx_orig = ((double)cx - (double)x_offset) / scale;
        double cy_orig = ((double)cy - (double)y_offset) / scale;
        double w_orig = (double)w / scale;
        double h_orig = (double)h / scale;

        int x1 = (int)(cx_orig - w_orig / 2.0);
        int y1 = (int)(cy_orig - h_orig / 2.0);
        int x2 = (int)(cx_orig + w_orig / 2.0);
        int y2 = (int)(cy_orig + h_orig / 2.0);

        x1 = std::max(0, std::min(orig_w, x1));
        y1 = std::max(0, std::min(orig_h, y1));
        x2 = std::max(0, std::min(orig_w, x2));
        y2 = std::max(0, std::min(orig_h, y2));

        std::vector<float> mask_coeff;
        if (is_seg_model) {
            int coeff_start = 4 + num_classes;
            int coeff_end = coeff_start + 32;
            if (coeff_end <= cols) {
                for (int k = coeff_start; k < coeff_end; ++k) {
                    mask_coeff.push_back(dets(i, k));
                }
            }
        }

        all_boxes.push_back({(double)x1, (double)y1, (double)x2, (double)y2});
        all_scores.push_back((double)max_score);
        all_masks_coeff.push_back(mask_coeff);
    }

    if (all_boxes.empty()) {
        return detections;
    }

    py::ssize_t n_boxes = (py::ssize_t)all_boxes.size();
    auto boxes_arr = py::array_t<double>({n_boxes, (py::ssize_t)4});
    auto scores_arr = py::array_t<double>(n_boxes);
    auto bbuf = boxes_arr.mutable_unchecked<2>();
    auto sbuf = scores_arr.mutable_unchecked<1>();

    for (py::ssize_t i = 0; i < n_boxes; ++i) {
        bbuf(i, 0) = all_boxes[i][0];
        bbuf(i, 1) = all_boxes[i][1];
        bbuf(i, 2) = all_boxes[i][2];
        bbuf(i, 3) = all_boxes[i][3];
        sbuf(i) = all_scores[i];
    }

    py::list keep_indices = nms(boxes_arr, scores_arr, iou_threshold);

    py::list masks_nms;
    if (py::len(keep_indices) > 0 && is_seg_model && !proto_obj.is_none()) {
        py::ssize_t n_keep = py::len(keep_indices);
        std::vector<int> keep_vec(n_keep);
        for (py::ssize_t i = 0; i < n_keep; ++i) {
            keep_vec[i] = keep_indices[i].cast<int>();
        }

        auto boxes_nms = py::array_t<double>({n_keep, (py::ssize_t)4});
        auto bnbuf = boxes_nms.mutable_unchecked<2>();
        for (py::ssize_t i = 0; i < n_keep; ++i) {
            int idx = keep_vec[i];
            bnbuf(i, 0) = all_boxes[idx][0];
            bnbuf(i, 1) = all_boxes[idx][1];
            bnbuf(i, 2) = all_boxes[idx][2];
            bnbuf(i, 3) = all_boxes[idx][3];
        }

        int coeff_dim = (int)all_masks_coeff[0].size();
        auto masks_coeff_arr = py::array_t<float>({(py::ssize_t)n_keep, (py::ssize_t)coeff_dim});
        auto mcbuf = masks_coeff_arr.mutable_unchecked<2>();
        for (py::ssize_t i = 0; i < n_keep; ++i) {
            int idx = keep_vec[i];
            for (int j = 0; j < coeff_dim; ++j) {
                mcbuf(i, j) = all_masks_coeff[idx][j];
            }
        }

        py::object proto_arr = proto_obj;
        auto proto_ndim = proto_obj.cast<py::array_t<float>>().ndim();
        if (proto_ndim == 4) {
            proto_arr = proto_obj.attr("__getitem__")(0);
        }

        masks_nms = process_mask(
            proto_arr.cast<py::array_t<float>>(),
            masks_coeff_arr,
            boxes_nms,
            py::make_tuple(orig_h, orig_w),
            scale,
            offset,
            new_size
        );
    }

    for (py::ssize_t i = 0; i < py::len(keep_indices); ++i) {
        int idx = keep_indices[i].cast<int>();
        int x1 = (int)all_boxes[idx][0];
        int y1 = (int)all_boxes[idx][1];
        int x2 = (int)all_boxes[idx][2];
        int y2 = (int)all_boxes[idx][3];
        double score = all_scores[idx];

        py::object mask = py::none();
        if (i < py::len(masks_nms)) {
            mask = masks_nms[i];
            auto marr = mask.cast<py::array_t<uint8_t>>();
            auto mbuf = marr.unchecked<2>();
            long long sum = 0;
            for (int r = 0; r < mbuf.shape(0); ++r)
                for (int c = 0; c < mbuf.shape(1); ++c)
                    sum += mbuf(r, c);
            if (sum == 0) {
                auto new_mask = py::array_t<uint8_t>(orig_h * orig_w);
                auto nbuf = new_mask.mutable_unchecked<1>();
                for (int j = 0; j < orig_h * orig_w; ++j) nbuf(j) = 0;
                for (int r = y1; r < y2 && r < orig_h; ++r)
                    for (int c = x1; c < x2 && c < orig_w; ++c)
                        nbuf(r * orig_w + c) = 255;
                new_mask.resize({orig_h, orig_w});
                mask = new_mask;
            }
        }

        py::dict det;
        det["bbox"] = py::make_tuple(x1, y1, x2, y2);
        det["score"] = (float)score;
        det["class_id"] = 0;
        det["class_name"] = "hook";
        det["mask"] = mask;
        detections.append(det);
    }

    return detections;
}
