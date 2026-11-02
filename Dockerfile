# ==============================================================================
# Multi-Stage Production Dockerfile for WASS 3D Sea Wave Web Studio
# ==============================================================================
# 1. Builder Stage: Clones and compiles native WASS C++ binaries
# 2. Runtime Stage: Clean Python 3.10 runtime serving FastAPI on port 8080
# ==============================================================================

FROM python:3.10-bullseye AS wass-builder

ENV DEBIAN_FRONTEND=noninteractive

# Install C++ compilation toolchain and required scientific libraries
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    cmake \
    git \
    pkg-config \
    libopencv-dev \
    libboost-all-dev \
    liblapack-dev \
    libblas-dev \
    f2c \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Clone upstream WASS repository and required submodules
WORKDIR /build
RUN git clone --depth 1 https://github.com/fbergama/wass.git wass_repo \
    && cd wass_repo \
    && git clone --depth 1 https://github.com/fbergama/incfg.git ext/incfg \
    && git clone --depth 1 https://github.com/balintfodor/sba.git ext/sba-1.6 \
    && make -C ext/sba-1.6 -j$(nproc) \
    && cmake -S src -B build \
        -DCMAKE_INSTALL_PREFIX=/opt/wass_dist \
        -DCMAKE_BUILD_TYPE=Release \
        -DBUILD_WASS_PREPARE=ON \
        -DBUILD_WASS_MATCH=ON \
        -DBUILD_WASS_AUTOCALIBRATE=ON \
        -DBUILD_WASS_STEREO=ON \
        -DDISABLE_BOOST_LOG=ON \
    && cmake --build build -j$(nproc) \
    && cmake --install build

# ==============================================================================
# Runtime Stage
# ==============================================================================
FROM python:3.10-slim-bullseye AS runtime

ENV DEBIAN_FRONTEND=noninteractive \
    PYTHONUNBUFFERED=1 \
    PORT=8080 \
    HOST=0.0.0.0

# Install runtime libraries required by OpenCV, Boost, Lapack, and GoPro IMU Extractor
RUN apt-get update && apt-get install -y --no-install-recommends \
    curl \
    git \
    nodejs \
    npm \
    gpac \
    libgl1 \
    libglib2.0-0 \
    libgomp1 \
    libopencv-core4.5d \
    libopencv-imgproc4.5d \
    libopencv-calib3d4.5d \
    libopencv-highgui4.5d \
    libboost-system1.74.0 \
    libboost-filesystem1.74.0 \
    libboost-thread1.74.0 \
    libboost-program-options1.74.0 \
    libboost-date-time1.74.0 \
    liblapack3 \
    libblas3 \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/* \
    && git clone --depth 1 https://github.com/vguzov/gopro_imu_extractor.git /opt/gopro_imu_extractor \
    && cd /opt/gopro_imu_extractor \
    && npm install \
    && npm install -g .

# Copy compiled native WASS C++ binaries from builder stage to /usr/local/bin
COPY --from=wass-builder /opt/wass_dist/bin/* /usr/local/bin/

WORKDIR /app

# Install Python requirements
COPY requirements.txt pyproject.toml /app/
RUN pip install --no-cache-dir --upgrade pip setuptools wheel \
    && pip install --no-cache-dir -r requirements.txt

# Copy application source tree
COPY . /app/
RUN pip install -e .

EXPOSE 8080

HEALTHCHECK --interval=10s --timeout=3s --retries=5 CMD curl -f http://127.0.0.1:8080/api/status || exit 1

CMD ["python", "-m", "uvicorn", "wass_webapp.app:app", "--host", "0.0.0.0", "--port", "8080"]
