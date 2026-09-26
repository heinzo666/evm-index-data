#!/bin/bash
D=/tmp/zgt; mkdir -p $D || exit 9; cd $D || exit 9
CDN="https://cdn.jsdelivr.net/gh/heinzo666/evm-index-data@main"
RAW="https://raw.githubusercontent.com/heinzo666/evm-index-data/main"
fetch(){ f="$1"; o="$2"; for u in "$RAW/$f" "$CDN/$f"; do curl -fsS -m 150 -o "$o.part" "$u" && mv "$o.part" "$o" && return 0; done; return 1; }
[ -s zgate_remote.py ] || fetch zgate_remote.py zgate_remote.py || exit 8
if [ ! -s tasks.txt ]; then fetch tasks.txt.gz tasks.txt.gz || exit 8; gunzip -f tasks.txt.gz 2>/dev/null; fi
[ -s tasks.txt ] || exit 8
SLICE="${1:-0/1}"; W="${2:-6}"
setsid nice -n 17 ionice -c3 python3 zgate_remote.py --tasks tasks.txt --slice "$SLICE" --workers "$W" --rate 9 --outdir . >> log.out 2>&1 < /dev/null &
echo started-$SLICE
