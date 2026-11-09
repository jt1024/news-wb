#!/bin/zsh
# 双击运行：注册每天 09:00 的存活心跳到 macOS launchd
cd "$(dirname "$0")/.." || exit 1
/bin/zsh scripts/install_heartbeat.sh
echo ""
echo "安装日志：/Users/jt/Desktop/CC/news/news-app/data/heartbeat-install.log"
echo "窗口可关闭（心跳由 launchd 独立运行，不依赖本窗口）。"
