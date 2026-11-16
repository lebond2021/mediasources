"""把 dist/ 目录以 HTTP 提供出去，给出可直接填进 TVBox 的一条链接。

用法：
    py tools/serve.py                 # 默认 0.0.0.0:8080
    py tools/serve.py --port 8899
"""
from __future__ import annotations

import argparse
import functools
import http.server
import os
import socket
import sys

sys.stdout.reconfigure(encoding="utf-8")

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DIST = os.path.join(ROOT, "dist")


class Handler(http.server.SimpleHTTPRequestHandler):
    def end_headers(self):
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Cache-Control", "no-cache, no-store, must-revalidate")
        super().end_headers()

    def log_message(self, fmt, *args):
        sys.stderr.write("  %s - %s\n" % (self.address_string(), fmt % args))


def lan_ips() -> list[str]:
    ips = []
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        s.connect(("223.5.5.5", 53))
        ips.append(s.getsockname()[0])
        s.close()
    except Exception:
        pass
    try:
        for info in socket.getaddrinfo(socket.gethostname(), None, socket.AF_INET):
            ip = info[4][0]
            if ip not in ips and not ip.startswith("127."):
                ips.append(ip)
    except Exception:
        pass
    return ips


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--port", type=int, default=8080)
    ap.add_argument("--host", default="0.0.0.0")
    ap.add_argument("--dir", default=DIST)
    a = ap.parse_args()
    if not os.path.isdir(a.dir):
        print(f"目录不存在: {a.dir}（先跑 py -m tvh build）")
        return 1
    handler = functools.partial(Handler, directory=a.dir)
    srv = http.server.ThreadingHTTPServer((a.host, a.port), handler)
    print(f"服务中: {a.dir}")
    print(f"  本机   http://127.0.0.1:{a.port}/index.json")
    for ip in lan_ips():
        print(f"  局域网 http://{ip}:{a.port}/index.json")
    print("  Ctrl+C 停止")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        print("\n已停止")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
