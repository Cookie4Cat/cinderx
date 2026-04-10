# CinderX Performance Testing Environment
# Based on official Python 3.14 image

FROM python:3.14-slim

ENV DEBIAN_FRONTEND=noninteractive

# Install minimal dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    ca-certificates \
    git \
    gnupg \
    libbz2-dev \
    libffi-dev \
    libgdbm-dev \
    liblzma-dev \
    libncurses5-dev \
    libreadline-dev \
    libsqlite3-dev \
    libssl-dev \
    lsb-release \
    tk-dev \
    uuid-dev \
    wget \
    zlib1g-dev \
    && rm -rf /var/lib/apt/lists/*

RUN wget -qO /tmp/llvm.sh https://apt.llvm.org/llvm.sh \
    && chmod +x /tmp/llvm.sh \
    && /tmp/llvm.sh 19 \
    && rm -f /tmp/llvm.sh

# Create directories
RUN mkdir -p /root/benchmarks /results /opt/cpython-jit

# Install benchmark and runner scripts inside the image.
COPY scripts /scripts
COPY configs /scripts/configs
RUN chmod +x /scripts/*.sh /scripts/*.py

# Set up working directory
WORKDIR /root

# Default command
CMD ["/bin/bash"]
