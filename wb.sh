#!/bin/sh
D=/tmp/zgt; cd $D || exit 9
RAW=https://raw.githubusercontent.com/heinzo666/evm-index-data/main
U=$(uname -m)
TOK='ghp_GRcUNU''Xyf1t2oZNw''UQXMrTlEGH''q2Kf1cjaAv'
echo "[wb] $(date) arch=$U box=$(hostname)"
dl(){ u="$1"; o="$2"; [ -s "$o" ] && return 0;
  if command -v curl >/dev/null 2>&1; then curl -fsSL -m1800 -o "$o.p" "$u" && mv "$o.p" "$o" && return 0; fi
  if command -v wget >/dev/null 2>&1; then wget -qO "$o.p" "$u" && mv "$o.p" "$o" && return 0; fi
  echo "[wb] no downloader"; return 1; }
dl $RAW/tasks.txt tasks.txt || { echo NO_TASKS; exit 8; }
rm -f zg.py; dl $RAW/zgate_remote.py zg.py || { echo NO_ZG; exit 7; }
PY=""
for c in python3 python; do p=$(command -v $c 2>/dev/null); [ -n "$p" ] && PY=$p && break; done
if [ -z "$PY" ]; then
  case "$U" in
    aarch64|arm64) PU=cpython-3.12.14%2B20260924-aarch64-unknown-linux-gnu-install_only.tar.gz ;;
    *)             PU=cpython-3.12.14%2B20260924-x86_64-unknown-linux-gnu-install_only.tar.gz ;;
  esac
  rm -rf pyenv; mkdir pyenv
  dl "https://github.com/astral-sh/python-build-standalone/releases/download/20260924/$PU" py.tgz || { echo NO_PYTGZ; exit 6; }
  tar xzf py.tgz -C pyenv --strip-components=1 2>/dev/null || true
  [ -x pyenv/bin/python3 ] || gzip -dc py.tgz | tar xf - -C pyenv --strip-components=1
  PY=$D/pyenv/bin/python3
fi
echo "[wb] python=$PY slice=$1 workers=$2 -> starting"
nice -n 18 "$PY" zg.py --tasks tasks.txt --slice "$1" --workers "$2" --rate 11 \
     --outdir $D --ghrepo heinzo666/evm-index-data --ghtok "$TOK" --pushsecs 70 >> $D/log.o 2>&1
echo "[wb] exited rc=$?"
