# ========== 基础镜像 ==========
FROM condaforge/miniforge3:25.3.1-0

# 设置工作目录
WORKDIR /app

# 避免交互式安装卡住
ENV DEBIAN_FRONTEND=noninteractive

# 更新系统工具并安装基础依赖（含 gcc、make、git 等）
RUN apt-get update && apt-get install -y \
    build-essential \
    git \
    && rm -rf /var/lib/apt/lists/*

# ========== 创建 Conda 环境 ==========
# 这里直接用 conda 创建名为 vnpy 的环境并安装 ta-lib
RUN conda create -n vnpy python=3.12 -y && \
    conda run -n vnpy conda install -c conda-forge ta-lib -y

# ========== 环境变量 ==========
# 激活 conda 环境
ENV PATH /opt/conda/envs/vnpy/bin:$PATH
ENV CONDA_DEFAULT_ENV=vnpy

# ========== 配置镜像源 ==========
# 使用阿里云的 pip 镜像源
RUN pip config set global.index-url https://mirrors.aliyun.com/pypi/simple/

# ========== 安装 vnpy ==========
# RUN git clone https://ghfast.top/https://github.com/vnpy/vnpy.git && \
#     cd vnpy && pip install . && cd ..

# 安装 Plotly 依赖的 Chromium
RUN apt-get update && apt-get install -y wget gnupg2 && \
    wget -q -O - https://dl.google.com/linux/linux_signing_key.pub | apt-key add - && \
    echo "deb [arch=amd64] http://dl.google.com/linux/chrome/deb/ stable main" \
      > /etc/apt/sources.list.d/google-chrome.list && \
    apt-get update && \
    apt-get install -y google-chrome-stable && \
    rm -rf /var/lib/apt/lists/*

# 指定给 Kaleido 找浏览器
ENV PLOTLY_CHROME_PATH=/usr/bin/google-chrome

# ========== 安装其他 python 包 ==========
RUN pip install vnpy_ctp vnpy_ctabacktester vnpy_datamanager vnpy_ctastrategy vnpy_sqlite vnpy_portfoliostrategy vnpy_tqsdk kaleido python-dotenv pandas sqlalchemy psycopg[binary]

# ========== 默认启动命令 ==========
# CMD ["python", "-c", "import vnpy; print('VNPY environment ready!')"]
