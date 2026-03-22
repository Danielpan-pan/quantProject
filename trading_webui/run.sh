#!/bin/bash

# 期货程序化交易系统启动脚本

echo "========================================="
echo "期货程序化交易系统 - VNPY WebUI"
echo "========================================="

# 检查 Python 版本
python_version=$(python3 --version 2>&1 | awk '{print $2}')
echo "Python 版本: $python_version"

# 检查虚拟环境
# if [ ! -d "venv" ]; then
#     echo "未找到虚拟环境，正在创建..."
#     python3 -m venv venv
#     echo "虚拟环境创建成功"
# fi

# # 激活虚拟环境
# echo "激活虚拟环境..."
# source venv/bin/activate

# 安装依赖
if [ ! -f "venv/.installed" ]; then
    echo "安装依赖包..."
    pip install --upgrade pip
    pip install -r requirements.txt
    touch venv/.installed
    echo "依赖包安装完成"
else
    echo "依赖包已安装，跳过安装步骤"
fi

# 创建必要的目录
echo "创建必要的目录..."
mkdir -p logs
mkdir -p static/css
mkdir -p static/js
mkdir -p templates

# 检查配置文件
if [ ! -f "config.json" ]; then
    echo "配置文件不存在，将在首次运行时创建默认配置"
fi

# 启动应用
echo "========================================="
echo "启动交易系统..."
echo "访问地址: http://localhost:8080"
echo "按 Ctrl+C 停止服务"
echo "========================================="

python3 app.py

# 停止时清理
echo "服务已停止"

