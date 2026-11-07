#!/bin/zsh
# 双击/Terminal 打开即可执行：在真正的 Aqua GUI 会话中注册 launchd 服务。
cd /Users/jt/Desktop/CC/news/news-app || exit 1
echo "=== 正在注册政务新闻服务开机自启 ==="
bash scripts/install_launchd.sh
RC=$?
echo
echo "=== 安装脚本结束（退出码 $RC）==="
echo "安装日志：/Users/jt/Desktop/CC/news/news-app/data/launchd-install.log"
echo "窗口可关闭。"
