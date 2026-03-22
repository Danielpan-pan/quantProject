# HERMES Trading Bot

## 简介
HERMES Trading Bot 是一个基于 [vn.py](https://www.vnpy.org) 的量化交易策略框架。

## 安装指南
### 系统环境
1. conda 环境
   参考 [miniforge](https://github.com/conda-forge/miniforge?tab=readme-ov-file#install) 文档在本地安装 conda 环境
2. 网络环境
   自行配置相关代理

### Docker 环境 (推荐)
1. 安装 Docker
   参考 [Docker 官方文档](https://docs.docker.com/get-docker/) 安装 Docker

2. 获取 Github Token
   参考 [Creating a personal access token](https://docs.github.com/en/github/authenticating-to-github/creating-a-personal-access-token) 创建一个新的 Token，勾选 `repo` 权限

3. 克隆仓库
   下面的 `{GITHUB_TOKEN}` 替换为上一步获取的 Token
   ```
   git clone https://{GITHUB_TOKEN}@github.com/HermesRunner/hermes-vnpy.git
   cd hermes-vnpy
   ```

4. 构建 Docker 镜像
   ```
   docker build -t hermes-vnpy .
   ```

5. 运行 Docker 容器
   ```
   docker run -it --name vnpy -v "$PWD":/workspace hermes-vnpy /bin/bash
   ```

6. 安装 vnpy
   ```
   cd /workspace/vnpy
   bash install.sh
   ```

7. 配置 vnpy setting
   ```
   cp vt_setting.json ~/.vntrader/vt_setting.json
   ```

### Python 环境 (Old)
1. 创建全新的 conda env
    ```
    conda create -n vnpy python=3.12
    conda install -c conda-forge ta-lib -y
    ```
2. 克隆仓库
    ```
    gh repo clone HermesRunner/hermes-vnpy
    cd hermes-vnpy
    ```
3. 安装 vnpy_ctp
    ```
   git clone https://github.com/vnpy/vnpy_ctp.git
    cd vnpy_ctp
    pip install . 
    cd ..
    ```
5. 安装 vnpy
   ```
   pip install . 
   ```
6. 安装其他相关依赖
    ```
    pip install -r requirements.txt
    ```

## 使用指南
1. 启动 GUI
   ```
   python examples/veighna_trader/run.py
   ```

2. 配置数据源等
TODO

3. 测试回调
   运行文件 `python back_testing.py`

4. CTP 模拟盘交易
   a. 配置系统环境变量 `TQ_USERNAME` 和 `TQ_PASSWORD`，用于天勤数据源登录；`SIMNOW_USERID` 和 `SIMNOW_PASSWORD`交易所账号密码，用于模拟交易登录
   运行文件 `python sim_testing.py`，参考文件内注释修改配置


## 贡献代码
### 策略编写
目前策略都放在 `strategies` 目录下，参考 `strategies/template.py` 编写自己的策略。
