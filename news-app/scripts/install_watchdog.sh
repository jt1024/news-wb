#!/bin/zsh
# 注册「独立于 Web 服务的兜底守护」LaunchAgent：每 30 分钟自检一次。
#
# 与 09:00 心跳的区别：心跳只报状态，守护会自愈服务、补跑漏掉的抓取轮次、
# 补发报告，因此服务整个挂掉时也不会静默不推送。
#
# 注意：IDE/WorkBuddy 内嵌会话里 launchctl 写入 GUI domain 常被系统拒绝
# （Bootstrap failed: 5）。此时脚本会启动一个独立的 --loop 常驻进程兜底；
# 若在真正的 GUI 终端（双击 .command）运行，则交给 launchd 长期托管。
set -u
APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PLIST="$HOME/Library/LaunchAgents/com.jt.gov-news-watchdog.plist"
LABEL="com.jt.gov-news-watchdog"
DOMAIN="gui/$(id -u)"
LOG="$APP_DIR/data/watchdog-install.log"
PID_FILE="$APP_DIR/data/watchdog.pid"
mkdir -p "$APP_DIR/data"

stop_loop() {
  if [ -f "$PID_FILE" ]; then
    OLDPID=$(cat "$PID_FILE")
    if [ -n "$OLDPID" ] && kill -0 "$OLDPID" 2>/dev/null; then
      kill -TERM "$OLDPID" 2>/dev/null || true
      echo "   已停掉旧的常驻守护 PID $OLDPID"
    fi
    rm -f "$PID_FILE"
  fi
}

start_loop() {
  # 保底：launchd 注册不了时，也要有一层不依赖 Web 服务的常驻自检
  if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE")" 2>/dev/null; then
    echo "   常驻守护已在运行 PID $(cat "$PID_FILE")"
    return
  fi
  cd "$APP_DIR" || return 1
  nohup .venv/bin/python scripts/watchdog.py --loop \
    >> data/watchdog.out.log 2>&1 &
  echo $! > "$PID_FILE"
  echo "   已启动常驻守护 PID $(cat "$PID_FILE")（每 30 分钟自检）"
}

{
  echo "=== $(date '+%Y-%m-%d %H:%M:%S') 注册兜底守护 ==="
  cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>$APP_DIR/.venv/bin/python</string>
    <string>$APP_DIR/scripts/watchdog.py</string>
  </array>
  <key>WorkingDirectory</key><string>$APP_DIR</string>
  <key>StartInterval</key><integer>1800</integer>
  <key>RunAtLoad</key><true/>
  <key>StandardOutPath</key><string>$APP_DIR/data/watchdog.out.log</string>
  <key>StandardErrorPath</key><string>$APP_DIR/data/watchdog.err.log</string>
</dict>
</plist>
EOF
  plutil -lint "$PLIST" || { echo "plist 校验失败"; exit 1; }

  echo "1) 注册 LaunchAgent（每 30 分钟 + 登录时立即自检）"
  launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
  if launchctl bootstrap "$DOMAIN" "$PLIST"; then
    echo "   注册成功，由 launchd 托管"
    launchctl enable "$DOMAIN/$LABEL" 2>/dev/null || true
    stop_loop
  else
    echo "   当前会话无法写入 GUI launchd（IDE 内常见限制）"
    echo "   plist 已就位且为 enabled，下次登录/重启由 macOS 自动加载"
    echo "   本次启动常驻进程兜底"
    start_loop
  fi

  echo "2) 注册状态"
  launchctl list 2>/dev/null | grep "$LABEL" || echo "   当前会话未注册（不影响下次登录自动加载）"

  echo "3) 立即自检（dry-run：不推送、不自愈、不补跑，仅建立基线）"
  "$APP_DIR/.venv/bin/python" "$APP_DIR/scripts/watchdog.py" --dry-run | head -14
  echo "4) 状态文件：$APP_DIR/data/watchdog.state.json"
  echo "   运行日志：$APP_DIR/data/watchdog.log"
  echo "=== 结束 ==="
} 2>&1 | tee "$LOG"
