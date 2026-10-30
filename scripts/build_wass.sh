#!/usr/bin/env bash
# ==============================================================================
# Automated WASS C++ Compilation Script
# ==============================================================================
# Pulls from upstream repository (https://github.com/fbergama/wass.git),
# initializes submodules, sets up SBA (Sparse Bundle Adjustment), compiles with
# CMake, and installs binaries to /usr/local/bin.
# ==============================================================================

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_DIR="$(cd "${SCRIPT_DIR}/.." && pwd)"
BUILD_DIR="${ROOT_DIR}/wass_build_cache"
INSTALL_PREFIX="${1:-/usr/local}"

echo "========================================================================"
echo " Starting WASS C++ Automated Pull & Build Pipeline"
echo " Target Install Prefix: ${INSTALL_PREFIX}"
echo "========================================================================"

# 1. Verify / Install Apt Dependencies (if root/sudo available)
if command -v apt-get >/dev/null 2>&1; then
    echo "[1/6] Checking system build packages..."
    MISSING_PKGS=""
    for pkg in build-essential cmake git pkg-config libopencv-dev libboost-all-dev liblapack-dev libblas-dev; do
        if ! dpkg -s "$pkg" >/dev/null 2>&1; then
            MISSING_PKGS="${MISSING_PKGS} ${pkg}"
        fi
    done

    if [ -n "$MISSING_PKGS" ]; then
        echo "[1/6] Missing system packages: ${MISSING_PKGS}"
        if [ "$(id -u)" -eq 0 ]; then
            apt-get update -qq && apt-get install -y --no-install-recommends ${MISSING_PKGS}
        elif command -v sudo >/dev/null 2>&1 && sudo -n true >/dev/null 2>&1; then
            sudo -n apt-get update -qq && sudo -n apt-get install -y --no-install-recommends ${MISSING_PKGS}
        else
            echo "[NOTE] Sudo requires a password or is unavailable. To install missing packages, run:"
            echo "       sudo apt-get install -y ${MISSING_PKGS}"
            echo "       (In Docker and Codespaces, these packages are installed automatically via Dockerfile)"
        fi
    else
        echo "[1/6] All prerequisite apt packages are satisfied."
    fi
fi

# 2. Source Code Resolution (Local wass/ or git clone)
mkdir -p "${BUILD_DIR}"
WASS_SOURCE="${ROOT_DIR}/wass"

if [ ! -d "${WASS_SOURCE}/src" ]; then
    echo "[2/6] WASS source not found locally. Cloning from https://github.com/fbergama/wass.git..."
    git clone --depth 1 https://github.com/fbergama/wass.git "${BUILD_DIR}/wass_repo"
    WASS_SOURCE="${BUILD_DIR}/wass_repo"
else
    echo "[2/6] Using local WASS source from ${WASS_SOURCE}."
fi

# 3. Submodule Initialization (ext/incfg)
echo "[3/6] Ensuring submodules (ext/incfg) are initialized..."
mkdir -p "${WASS_SOURCE}/ext"
if [ ! -f "${WASS_SOURCE}/ext/incfg/incfg.hpp" ]; then
    if [ -d "${WASS_SOURCE}/.git" ]; then
        (cd "${WASS_SOURCE}" && git submodule update --init --recursive) || true
    fi
    if [ ! -f "${WASS_SOURCE}/ext/incfg/incfg.hpp" ]; then
        echo "  Cloning incfg library into ext/incfg..."
        git clone --depth 1 https://github.com/fbergama/incfg.git "${WASS_SOURCE}/ext/incfg"
    fi
fi

# 4. SBA (Sparse Bundle Adjustment) Library Setup
# (Fixes the dead Dais university HTTP mirror by cloning from GitHub)
echo "[4/6] Setting up SBA 1.6 library..."
SBA_DIR="${WASS_SOURCE}/ext/sba-1.6"
if [ ! -f "${SBA_DIR}/sba.h" ] || [ ! -f "${SBA_DIR}/libsba.a" ]; then
    if [ ! -d "${SBA_DIR}" ]; then
        echo "  Cloning sba library from GitHub mirror..."
        git clone --depth 1 https://github.com/balintfodor/sba.git "${SBA_DIR}"
    fi
    if [ ! -f "${SBA_DIR}/libsba.a" ]; then
        echo "  Compiling libsba.a..."
        make -C "${SBA_DIR}" libsba.a -j"$(nproc 2>/dev/null || echo 2)"
    fi
fi

# 5. CMake Configuration & Compilation
echo "[5/6] Configuring and compiling WASS C++ binaries with CMake..."
CMAKE_BUILD="${BUILD_DIR}/cmake_build"
mkdir -p "${CMAKE_BUILD}"

cmake -S "${WASS_SOURCE}/src" -B "${CMAKE_BUILD}" \
    -DCMAKE_INSTALL_PREFIX="${INSTALL_PREFIX}" \
    -DCMAKE_BUILD_TYPE=Release \
    -DBUILD_WASS_PREPARE=ON \
    -DBUILD_WASS_MATCH=ON \
    -DBUILD_WASS_AUTOCALIBRATE=ON \
    -DBUILD_WASS_STEREO=ON \
    -DDISABLE_BOOST_LOG=ON

cmake --build "${CMAKE_BUILD}" -j"$(nproc 2>/dev/null || echo 2)"

# 6. Installation
echo "[6/6] Installing binaries to ${INSTALL_PREFIX}/bin..."
if [ "$(id -u)" -eq 0 ] || [ -w "${INSTALL_PREFIX}/bin" ]; then
    cmake --install "${CMAKE_BUILD}"
elif command -v sudo >/dev/null 2>&1 && sudo -n true >/dev/null 2>&1; then
    sudo -n cmake --install "${CMAKE_BUILD}"
else
    # Fallback to user-local ~/.local/bin
    USER_BIN="${HOME}/.local/bin"
    mkdir -p "${USER_BIN}"
    cmake -S "${WASS_SOURCE}/src" -B "${CMAKE_BUILD}" -DCMAKE_INSTALL_PREFIX="${HOME}/.local"
    cmake --install "${CMAKE_BUILD}"
    INSTALL_PREFIX="${HOME}/.local"
fi

# Verification
echo "========================================================================"
echo " WASS C++ Build Verification:"
for bin in wass_prepare wass_match wass_autocalibrate wass_stereo; do
    P="$(command -v "$bin" 2>/dev/null || echo "${INSTALL_PREFIX}/bin/${bin}")"
    if [ -x "$P" ]; then
        echo "  [FOUND] $bin -> $P"
    else
        echo "  [WARNING] $bin not found at expected location $P"
    fi
done
echo "========================================================================"
echo " WASS C++ Build Complete!"
echo "========================================================================"
