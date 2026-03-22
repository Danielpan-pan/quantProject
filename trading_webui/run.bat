@echo off
chcp 65001 >nul
setlocal enabledelayedexpansion

echo =========================================
echo 期货程序化交易系统 - VNPY WebUI
echo =========================================

REM 检查 Python
python --version >nul 2>&1
if errorlevel 1 (
    echo 错误: 未找到 Python，请先安装 Python 3.10+
    pause
    exit /b 1
)

echo Python 版本:
python --version

REM 检查虚拟环境
if not exist "venv" (
    echo 未找到虚拟环境，正在创建...
    python -m venv venv
    echo 虚拟环境创建成功
)

REM 激活虚拟环境
echo 激活虚拟环境...
call venv\Scripts\activate.bat

REM 安装依赖
if not exist "venv\.installed" (
    echo 安装依赖包...
    python -m pip install --upgrade pip
    pip install -r requirements.txt
    echo. > venv\.installed
    echo 依赖包安装完成
) else (
    echo 依赖包已安装，跳过安装步骤
)

REM 创建必要的目录
echo 创建必要的目录...
if not exist "logs" mkdir logs
if not exist "static\css" mkdir static\css
if not exist "static\js" mkdir static\js
if not exist "templates" mkdir templates

REM 检查配置文件
if not exist "config.json" (
    echo 配置文件不存在，将在首次运行时创建默认配置
)

REM 启动应用
echo =========================================
echo 启动交易系统...
echo 访问地址: http://localhost:8080
echo 按 Ctrl+C 停止服务
echo =========================================

python app.py

REM 停止时清理
echo 服务已停止
pause

