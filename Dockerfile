ARG CUDA_VERSION="12.4.1"
ARG UBUNTU_VERSION="22.04"
ARG DOCKER_FROM=nvidia/cuda:${CUDA_VERSION}-cudnn-devel-ubuntu${UBUNTU_VERSION}

# Base NVidia CUDA Ubuntu image
FROM ${DOCKER_FROM} AS base

# System dependencies
RUN apt-get update -y && \
    apt-get install -y \
    python3 python3-pip python3-venv \
    openssh-server openssh-client \
    git git-lfs wget vim zip unzip curl \
    libgl1-mesa-glx libegl1-mesa-dev libglib2.0-0 \
    ninja-build python3.10-venv python3.10-distutils && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/*
RUN apt-get update && apt-get install -y jq


# Environment configuration
ENV PATH="/usr/local/cuda/bin:/usr/bin:${PATH}"
ENV CUDA_HOME=/usr/local/cuda
ENV LD_LIBRARY_PATH=${CUDA_HOME}/lib64:${LD_LIBRARY_PATH}
ENV CPATH=/usr/local/cuda/include

# Install PyTorch
ARG PYTORCH="2.5.1"
ARG CUDA="124"
RUN pip3 install --no-cache-dir -U \
    torch==${PYTORCH} \
    torchvision \
    torchaudio \
    --extra-index-url https://download.pytorch.org/whl/cu${CUDA}

#Install HF_HUB
RUN pip3 install huggingface_hub[hf-transfer]
# Install core Python dependencies
COPY requirements.txt /
RUN pip3 install -r /requirements.txt
RUN mkdir -p /output && \
    chown -R 1000:1000 /output

# Clone ComfyUI and core nodes
RUN git clone https://github.com/comfyanonymous/ComfyUI.git && \
    cd ComfyUI && \
    pip3 install -r requirements.txt && \
    cd custom_nodes && \
    git clone https://github.com/ltdrdata/ComfyUI-Manager.git && \
    git clone https://github.com/pythongosssss/ComfyUI-Custom-Scripts.git

# Install additional custom nodes
RUN cd /ComfyUI/custom_nodes && \
    git clone https://github.com/kijai/ComfyUI-KJNodes.git && \
    cd ComfyUI-KJNodes && pip3 install -r requirements.txt && \
    cd .. && git clone https://github.com/cubiq/ComfyUI_essentials.git && \
    cd ComfyUI_essentials && pip3 install -r requirements.txt && \
    cd .. && git clone https://github.com/rgthree/rgthree-comfy.git && \
    cd rgthree-comfy && pip3 install -r requirements.txt && \
    cd .. && git clone https://github.com/crystian/ComfyUI-Crystools.git && \
    cd ComfyUI-Crystools && pip3 install -r requirements.txt && \
    cd .. && git clone https://github.com/Acly/comfyui-tooling-nodes && \
    cd .. && git clone https://github.com/Kosinkadink/ComfyUI-VideoHelperSuite.git && \
    cd ComfyUI-VideoHelperSuite && pip3 install -r requirements.txt && \
    cd .. && git clone https://github.com/WASasquatch/was-node-suite-comfyui.git && \
    cd was-node-suite-comfyui && pip3 install -r requirements.txt && \
    cd .. && git clone https://github.com/chrisgoringe/cg-use-everywhere.git

# Cleanup problematic packages
RUN pip uninstall -y sageattention xformers

# Copy application files

# Application files
COPY --chmod=755 start.sh /start.sh
COPY --chmod=755 scripts/ /scripts/
COPY --chmod=644 config/comfy.settings.json /ComfyUI/user/default/
COPY api/ /api
COPY workflows/ /workflows
RUN chmod +x start.sh scripts/*.sh

    

# Expose ports
#FastAPI
EXPOSE 8000 
#ComfyUI (internal only)
EXPOSE 8188 
# Jupyter (optional)
EXPOSE 8888
 
RUN apt-get update && \
    apt-get install -y dos2unix && \
    find . -type f -name "*.sh" -exec dos2unix {} + && \
    apt-get purge -y dos2unix && \
    apt-get autoremove -y

# Set working directory and entrypoint
WORKDIR /
CMD [ "/start.sh" ]
