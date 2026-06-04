cmake_minimum_required(VERSION 3.15)
project(dobot_core)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)

find_package(pybind11 REQUIRED)

pybind11_add_module(dobot_core
    src/pybind_module.cpp
    src/transforms.cpp
    src/nms.cpp
    src/yolo.cpp
    src/depth_position.cpp
)

target_include_directories(dobot_core PRIVATE
    ${CMAKE_CURRENT_SOURCE_DIR}/include
)

set_target_properties(dobot_core PROPERTIES
    LIBRARY_OUTPUT_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}/.."
    RUNTIME_OUTPUT_DIRECTORY "${CMAKE_CURRENT_SOURCE_DIR}/.."
)
