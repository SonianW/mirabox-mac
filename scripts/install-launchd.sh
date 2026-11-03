#!/usr/bin/env bash
# Install (or reinstall) the launchd agent so mirabox-mac starts at login.
# Usage: scripts/install-launchd.sh          install and start
#        scripts/install-launchd.sh remove   stop and remove
set -euo pipefail

LABEL=com.sonianw.mirabox-mac
REPO="$(cd "$(dirname "$0")/.." && pwd)"
PLIST="$HOME/Library/LaunchAgents/$LABEL.plist"
UV="$(command -v uv || true)"

if [[ "${1:-}" == "remove" ]]; then
  launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
  rm -f "$PLIST"
  echo "removed $LABEL"
  exit 0
fi

[[ -n "$UV" ]] || { echo "uv not found on PATH; install it first (https://docs.astral.sh/uv/)" >&2; exit 1; }
[[ -f "$HOME/.config/mirabox-mac/config.json" ]] || {
  echo "no config at ~/.config/mirabox-mac/config.json; run: mkdir -p ~/.config/mirabox-mac && cp $REPO/config.example.json ~/.config/mirabox-mac/config.json" >&2
  exit 1
}

mkdir -p "$(dirname "$PLIST")" "$HOME/Library/Logs"
sed -e "s|__UV__|$UV|g" -e "s|__REPO__|$REPO|g" -e "s|__HOME__|$HOME|g" \
  "$REPO/launchd/$LABEL.plist.template" > "$PLIST"

launchctl bootout "gui/$(id -u)/$LABEL" 2>/dev/null || true
launchctl bootstrap "gui/$(id -u)" "$PLIST"
launchctl kickstart -k "gui/$(id -u)/$LABEL"
echo "installed $LABEL; log: ~/Library/Logs/mirabox-mac.log"
