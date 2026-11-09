#!/bin/zsh
# 注册每天 09:00 的独立存活心跳（LaunchAgent）。
# 它与应用服务进程完全解耦：即使 Web 服务整个挂掉，也能推红色告警到飞书。
set -u
APP_DIR="$(cd "$(dirname "$0")/.." && pwd)"
PLIST="$HOME/Library/LaunchAgents/com.jt.gov-news-heartbeat.plist"
LABEL="com.jt.gov-news-heartbeat"
DOMAIN="gui/$(id -u)"
LOG="$APP_DIR/data/heartbeat-install.log"
mkdir -p "$APP_DIR/data"

{
  echo "=== $(date '+%Y-%m-%d %H:%M:%S') 注册 09:00 存活心跳 ==="
  cat > "$PLIST" <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>$LABEL</string>
  <key>ProgramArguments</key>
  <array>
    <string>$APP_DIR/.venv/bin/python</string>
    <string>$APP_DIR/scripts/heartbeat.py</string>
  </array>
  <key>WorkingDirectory</key><string>$APP_DIR</string>
  <key>StartCalendarInterval</key>
  <dict><key>Hour</key><integer>9</integer><key>Minute</key><integer>0</integer></dict>
  <key>RunAtLoad</key><false/>
  <key>StandardOutPath</key><string>$APP_DIR/data/heartbeat.out.log</string>
  <key>StandardErrorPath</key><string>$APP_DIR/data/heartbeat.err.log</string>
</dict>
</plist>
EOF
  plutil -lint "$PLIST" || { echo "plist 校验失败"; exit 1; }

  echo "1) 注册 LaunchAgent"
  launchctl bootout "$DOMAIN/$LABEL" 2>/dev/null || true
  REGISTERED=0
  if launchctl bootstrap "$DOMAIN" "$PLIST" 2>/dev/null; then
    # 只信返回码会把「临时会话注册」误报成成功；必须用 print 复核服务
    # 是否真的留在持久 GUI 域。
    if launchctl print "$DOMAIN/$LABEL" >/dev/null 2>&1; then
      REGISTERED=1
    fi
  fi
  launchctl enable "$DOMAIN/$LABEL" 2>/dev/null || true
  if [ "$REGISTERED" = 1 ]; then
    echo "   注册成功并已验证（launchd 托管，每天 09:00）"
  else
    echo "   服务未进入持久 GUI 域（bootstrap 可能落在临时会话）"
    echo "   plist 已就位且为 enabled，下次登录/重启由 macOS 自动加载"
    echo "   也可在访达双击 scripts/run_heartbeat_install.command 完成注册"
  fi

  echo "2) 注册状态"
  launchctl list 2>/dev/null | grep "$LABEL" || echo "   当前会话未注册"
  echo "3) 立即自检（不推送）"
  "$APP_DIR/.venv/bin/python" "$APP_DIR/scripts/heartbeat.py" --dry-run --no-period | head -12
  echo "=== 结束 ==="
} 2>&1 | tee "$LOG"
