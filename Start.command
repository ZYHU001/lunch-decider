#!/bin/zsh
cd -- "${0:A:h}" || exit 1
export LUNCH_DECIDER_HOST=0.0.0.0
if curl -fsS -o /dev/null http://127.0.0.1:4173/ 2>/dev/null; then
  open http://127.0.0.1:4173/
  exit 0
fi
(
  for attempt in {1..30}; do
    if curl -fsS -o /dev/null http://127.0.0.1:4173/ 2>/dev/null; then
      open http://127.0.0.1:4173/
      exit 0
    fi
    sleep 0.2
  done
  print -u2 "服务启动后仍无法打开页面，请访问 http://127.0.0.1:4173/"
) &
python3 server.py
