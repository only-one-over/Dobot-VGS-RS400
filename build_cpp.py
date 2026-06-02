#!/usr/bin/env python3
import subprocess
import sys
import os
import glob
import shutil

def main():
    project_root = os.path.dirname(os.path.abspath(__file__))
    cpp_dir = os.path.join(project_root, "cpp_core")
    build_dir = os.path.join(cpp_dir, "build")
    os.makedirs(build_dir, exist_ok=True)

    cmake_args = [f"-DPYTHON_EXECUTABLE={sys.executable}"]

    try:
        import pybind11
        cmake_dir = pybind11.get_cmake_dir()
        cmake_args.append(f"-Dpybind11_DIR={cmake_dir}")
    except ImportError:
        pass

    cmake_cmd = [
        sys.executable, "-m", "cmake", "-S", cpp_dir, "-B", build_dir
    ] + cmake_args
    print(f"Running CMake configure: {' '.join(cmake_cmd)}")
    subprocess.check_call(cmake_cmd)

    build_cmd = [sys.executable, "-m", "cmake", "--build", build_dir, "--config", "Release"]
    print(f"Running CMake build: {' '.join(build_cmd)}")
    subprocess.check_call(build_cmd)

    patterns = [
        os.path.join(project_root, "Release", "dobot_core*"),
        os.path.join(build_dir, "Release", "dobot_core*"),
        os.path.join(build_dir, "dobot_core*"),
    ]
    found = False
    for pattern in patterns:
        for f in glob.glob(pattern):
            if os.path.isfile(f) and (f.endswith('.pyd') or f.endswith('.so')):
                dest = os.path.join(project_root, os.path.basename(f))
                shutil.copy2(f, dest)
                print(f"Copied {f} -> {dest}")
                found = True
    if not found:
        print("Warning: Could not find compiled dobot_core module")
    else:
        print("Build successful! You can now 'import dobot_core'")

if __name__ == "__main__":
    main()
