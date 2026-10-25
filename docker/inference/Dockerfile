# Separate from ROS Humble; never install these libraries into the mapping image.
FROM ubuntu:24.04
SHELL ["/bin/bash", "-o", "pipefail", "-c"]
ARG TRT_VERSION=10.16.2.10-1+cuda13.2
RUN apt-get update && apt-get install -y --no-install-recommends ca-certificates curl \
    && curl -fsSL https://repo.download.nvidia.com/jetson/jetson-ota-public.asc \
       -o /usr/share/keyrings/jetson-ota-public.asc \
    && echo 'deb [signed-by=/usr/share/keyrings/jetson-ota-public.asc] https://repo.download.nvidia.com/jetson/common r39.2 main' \
       > /etc/apt/sources.list.d/jetson.list \
    && apt-get update && apt-get install -y --no-install-recommends \
       python3 python3-numpy python3-opencv \
       python3-libnvinfer=${TRT_VERSION} libnvinfer10=${TRT_VERSION} \
       libnvinfer-plugin10=${TRT_VERSION} libnvonnxparsers10=${TRT_VERSION} \
       libnvinfer-bin=${TRT_VERSION} cuda-cudart-13-2 \
    && rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY scripts/trt_worker.py /app/trt_worker.py
USER 1000:1000
ENV HOME=/tmp NVIDIA_VISIBLE_DEVICES=all NVIDIA_DRIVER_CAPABILITIES=compute,utility
ENTRYPOINT ["python3", "/app/trt_worker.py"]
