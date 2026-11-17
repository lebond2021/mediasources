"""调试：对若干直播地址跑一遍 measure()，看失败原因与速度。"""
from __future__ import annotations

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
sys.stdout.reconfigure(encoding="utf-8")

from tools.build_live import measure  # noqa: E402

URLS = [
    "https://ldocctvwbcdtxy.liveplay.myqcloud.com/ldocctvwbcd/cdrmldcctv1_1_ud.m3u8",
    "https://ldocctvwbcdtxy.liveplay.myqcloud.com/ldocctvwbcd/cdrmldcctv2_1_ud.m3u8",
    "https://ldocctvwbcdtxy.liveplay.myqcloud.com/ldocctvwbcd/cdrmldcctv6_1_ud.m3u8",
    "https://ldocctvwbcdbd.a.bdydns.com/ldocctvwbcd/cdrmldcctv8_1/index.m3u8?BR=hd",
    "https://iptv.yang-1989.xyz/cn/jrsgq9.m3u8",
    "http://liveplay.myqcloud.com/ldocctvwbcd/cdrmldcctv1_1_ud.m3u8",
]

for u in URLS:
    r = measure(u)
    print(f"{'OK ' if r else 'FAIL'} {u[:80]}")
    if r:
        print(f"     {r['kbps']} KB/s  {r['res']}  {r['kind']}  media={r['media'][:90]}")
