#!/bin/zsh
# 把政务新闻服务注册为 macOS 登录自启（launchd LaunchAgent）。
#
# 注意：WorkBuddy / IDE 内嵌会话里 launchctl 写入 GUI domain 常被系统拒绝
# （Bootstrap failed: 5: Input/output error）。此时脚本不会留下停摆的服务：
#   - 已经停掉的旧进程会自动恢复；
#   - plist 仍留在 ~/Library/LaunchAgents 且为 enabled，下次登录由 macOS 自动加载。
set -u
PLIST="$HOME/Library/LaunchAgents/com.jt.gov-news.plist"
APP_DIR="/Users/jt/Desktop/CC/news/news-app"
LOG="$APP_DIR/data/launchd-install.log"
DOMAIN="gui/$(id -u)"
LABEL="com.jt.gov-news"

start_temp_server() {
  # 保底：确保 8300 上有服务在跑（脱离 launchctl 也能用）
  if curl -s -o /dev/null --max-time 2 http://127.0.0.1:8300/; then
    echo "服务已在运行，无需兜底拉起"
    return
  fi
  echo "注册未生效，恢复临时服务"
  cd "$APP_DIR" || return 1
  nohup .venv/bin/uvicorn app.main:app --host 127.0.0.1 --port 8300 \
    >> data/server.out.log 2>&1 &
  for i in 1 2 3 4 5 6 7 8; do
    CODE=$(curl -s -o /dev/null -w "%{http_code}" --max-time 2 http://127.0.0.1:8300/ 2>/dev/null || true)
    [ "$CODE" = "200" ] && break
    sleep 1
  done
  echo "兜底服务 HTTP: ${CODE:-无响应}"
}

{
  echo "=== $(date '+%Y-%m-%d %H:%M:%S') 安装 launchd 自启 ==="
  if [ ! -f "$PLIST" ]; then echo "缺少 plist: $PLIST"; start_temp_server; exit 1; fi
  plutil -lint "$PLIST" || { start_temp_server; exit 1; }

  echo "1) 尝试注册（不先停服务，避免失败留空窗）"
  launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
  if launchctl bootstrap "$DOMAIN" "$PLIST"; then
    echo "   注册成功"
    launchctl enable "$DOMAIN/$LABEL" 2>/dev/null || true
    # 注册成功后才替换掉旧的临时进程，让 launchd 接管（KeepAlive 会自动拉起）
    OLDPID=$(lsof -ti :8300 -sTCP:LISTEN 2>/dev/null || true)
    if [ -n "$OLDPID" ]; then
      echo "2) 停掉旧进程 PID ${OLDPID}，交给 launchd"
      kill -TERM "$OLDPID"
      for i in 1 2 3 4 5 6 7 8; do
        lsof -ti :8300 -sTCP:LISTEN >/dev/null 2>&1 || break
        sleep 1
      done
    fi
    launchctl kickstart -k "$DOMAIN/$LABEL" 2>/dev/null || true
  else
    echo "   注册失败（当前会话无 GUI launchd 写入权限）"
    echo "   但 plist 已就位且为 enabled，下次登录/重启由 macOS 自动加载"
  fi

  echo "3) 注册状态"
  launchctl list 2>/dev/null | grep "$LABEL" || echo "   当前会话未注册（不影响下次登录自动加载）"
  launchctl print-disabled "$DOMAIN" 2>&1 | grep -i "$LABEL" || true

  echo "4) 服务可用性"
  CODE=""
  for i in 1 2 3 4 5 6 7 8 9 10; do
    CODE=$(curl -s -o /dev/null -w "%{http_code}" --max-time 2 http://127.0.0.1:8300/ 2>/dev/null || true)
    [ "$CODE" = "200" ] && break
    sleep 1
  done
  if [ "$CODE" != "200" ]; then start_temp_server; fi
  echo "   首页 HTTP: ${CODE:-无响应}"
  echo "   标准输出日志: $APP_DIR/data/launchd.out.log"
  echo "   错误日志: $APP_DIR/data/launchd.err.log"
  echo "   应用运行日志: $APP_DIR/data/server.out.log"
  echo "=== 结束 ==="
} 2>&1 | tee "$LOG"
