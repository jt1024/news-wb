#!/bin/zsh
# 双击/Terminal 打开即可执行：在真正的 Aqua GUI 会话中注册兜底守护。
cd /Users/jt/Desktop/CC/news/news-app || exit 1
echo "=== 正在注册「服务掉线也照常告警/补跑」的兜底守护 ==="
zsh scripts/install_watchdog.sh
RC=$?
echo
echo "=== 安装脚本结束（退出码 $RC）==="
echo "安装日志：/Users/jt/Desktop/CC/news/news-app/data/watchdog-install.log"
echo "窗口可关闭（守护由 launchd 或后台进程独立运行，不依赖本窗口）。"
