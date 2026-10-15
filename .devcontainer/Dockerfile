FROM mcr.microsoft.com/devcontainers/python:3.10

ENV DEBIAN_FRONTEND=noninteractive

# Install essential Linux graphics & system libraries for OpenCV and background daemons
RUN apt-get update && apt-get install -y --no-install-recommends \
    libgl1 \
    libglib2.0-0 \
    libgomp1 \
    curl \
    tmux \
    procps \
    && apt-get clean \
    && rm -rf /var/lib/apt/lists/*

# Upgrade pip and packaging tools
RUN pip install --no-cache-dir --upgrade pip setuptools wheel
