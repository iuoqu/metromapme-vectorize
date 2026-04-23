#!/usr/bin/env python3
"""Check if mis-attributed stations are the actual terminal/other legit stations with wrong names."""
import sys, math, json
from pathlib import Path

data = json.load(open('public/v2/stations.json'))

# Dump all L3 stations sorted by y (north-south)
print("=== All L3 detected stations by y ===")
for sid, s in sorted(data['stations'].items(),
                     key=lambda kv: (kv[1]['line'], kv[1]['y'])):
    if s['line'] == '3':
        tg = s['transfer_group'] or ''
        print(f"  {sid}: ({s['x']:.0f},{s['y']:.0f}) {s['name_zh']} {tg}")

print()
print("=== All L11 detected stations near (2329, 3063) ===")
target_x, target_y = 2329, 3063
for sid, s in data['stations'].items():
    if s['line'] == '11':
        d = math.hypot(s['x']-target_x, s['y']-target_y)
        if d < 300:
            tg = s['transfer_group'] or ''
            print(f"  {sid}: ({s['x']:.0f},{s['y']:.0f}) {s['name_zh']} {tg} d={d:.0f}")

print()
print("=== All L15 detected stations sorted by y (looking for 石龙路 area) ===")
for sid, s in sorted(data['stations'].items(),
                     key=lambda kv: (kv[1]['line'], kv[1]['y'])):
    if s['line'] == '15':
        tg = s['transfer_group'] or ''
        print(f"  {sid}: ({s['x']:.0f},{s['y']:.0f}) {s['name_zh']} {tg}")
