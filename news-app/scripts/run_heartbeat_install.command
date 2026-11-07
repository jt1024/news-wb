#!/bin/zsh
# 双击运行：注册每天 09:00 的存活心跳到 macOS launchd
cd "$(dirname "$0")/.." || exit 1
/bin/zsh scripts/install_heartbeat.sh
echo ""
echo "按回车键关闭窗口..."
read -r _
