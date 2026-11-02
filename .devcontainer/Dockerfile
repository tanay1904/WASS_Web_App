FROM mcr.microsoft.com/devcontainers/python:3.10

ENV DEBIAN_FRONTEND=noninteractive

# 1. Install system utilities and C++ build toolchain for WASS
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    cmake \
    git \
    pkg-config \
    curl \
    tmux \
    procps \
    libgl1 \
    libglib2.0-0 \
    libgomp1 \
    libopencv-dev \
    libboost-all-dev \
    liblapack-dev \
    libblas-dev \
    f2c \
    nodejs \
    npm \
    gpac \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# 2. Upgrade pip and packaging tools
RUN pip install --no-cache-dir --upgrade pip setuptools wheel

# 3. Pull from upstream WASS repo, initialize submodules & SBA, and compile native C++ binaries
RUN git clone --depth 1 https://github.com/fbergama/wass.git /opt/wass_source \
    && cd /opt/wass_source \
    && git clone --depth 1 https://github.com/fbergama/incfg.git ext/incfg \
    && git clone --depth 1 https://github.com/balintfodor/sba.git ext/sba-1.6 \
    && make -C ext/sba-1.6 -j$(nproc) \
    && cmake -S src -B build \
        -DCMAKE_INSTALL_PREFIX=/usr/local \
        -DCMAKE_BUILD_TYPE=Release \
        -DBUILD_WASS_PREPARE=ON \
        -DBUILD_WASS_MATCH=ON \
        -DBUILD_WASS_AUTOCALIBRATE=ON \
        -DBUILD_WASS_STEREO=ON \
        -DDISABLE_BOOST_LOG=ON \
    && cmake --build build -j$(nproc) \
    && cmake --install build \
    && rm -rf /opt/wass_source/build

# 4. Install GoPro IMU Extractor (vguzov/gopro_imu_extractor)
RUN git clone --depth 1 https://github.com/vguzov/gopro_imu_extractor.git /opt/gopro_imu_extractor \
    && cd /opt/gopro_imu_extractor \
    && npm install \
    && npm install -g .
