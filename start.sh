#!/bin/bash

echo "💰 财务数据分析系统启动脚本"
echo "================================"

# 检查Python环境
if ! command -v python &> /dev/null; then
    echo "❌ 未找到Python，请先安装Python"
    exit 1
fi

# 检查依赖文件
if [ ! -f "requirements.txt" ]; then
    echo "❌ 未找到requirements.txt文件"
    exit 1
fi

# 安装依赖
echo "📦 检查并安装依赖..."
pip install -r requirements.txt

# 检查必要文件
required_files=("app.py" "analysis_multi.py" "analysis_malaysia.py" "index.html")
for file in "${required_files[@]}"; do
    if [ ! -f "$file" ]; then
        echo "❌ 缺少必要文件: $file"
        exit 1
    fi
done

echo "✅ 所有依赖已就绪"
echo ""
echo "🚀 启动Web服务器..."
echo "📊 访问地址: http://localhost:8080"
echo "💡 使用 Ctrl+C 停止服务器"
echo ""

# 启动Flask应用
python app.py 