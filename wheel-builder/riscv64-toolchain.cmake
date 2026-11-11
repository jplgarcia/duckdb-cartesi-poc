# CMake toolchain for cross-compiling to linux/riscv64 (Cartesi Machine target).
set(CMAKE_SYSTEM_NAME Linux)
set(CMAKE_SYSTEM_PROCESSOR riscv64)

set(CMAKE_C_COMPILER riscv64-linux-gnu-gcc)
set(CMAKE_CXX_COMPILER riscv64-linux-gnu-g++)

set(CMAKE_FIND_ROOT_PATH /usr/riscv64-linux-gnu)
# Build tools (python, ninja) come from the host.
set(CMAKE_FIND_ROOT_PATH_MODE_PROGRAM NEVER)
# Libraries must come from the riscv64 sysroot.
set(CMAKE_FIND_ROOT_PATH_MODE_LIBRARY ONLY)
# Python/NumPy headers and nanobind's CMake config live outside the sysroot.
set(CMAKE_FIND_ROOT_PATH_MODE_INCLUDE BOTH)
set(CMAKE_FIND_ROOT_PATH_MODE_PACKAGE BOTH)
