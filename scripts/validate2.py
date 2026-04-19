#!/usr/bin/env python3
"""Summarize validation errors."""
import json
from pathlib import Path

data = json.load(open('public/v2/stations.json'))

OFFICIAL = {
    "3": ["江杨北路","铁力路","友谊路","宝杨路","水产路","淞滨路","张华浜","淞发路","长江南路","殷高西路","江湾镇","大柏树","赤峰路","虹口足球场","东宝兴路","宝山路","上海火车站","中潭路","镇坪路","曹杨路","金沙江路","中山公园","延安西路","虹桥路","宜山路","漕溪路","龙漕路","石龙路","上海南站"],
    "4": ["宜山路","虹桥路","延安西路","中山公园","金沙江路","曹杨路","镇坪路","中潭路","上海火车站","宝山路","海伦路","临平路","大连路","杨树浦路","浦东大道","世纪大道","向城路","蓝村路","塘桥","南浦大桥","西藏南路","鲁班路","大木桥路","东安路","上海体育场","上海体育馆"],
    "9": ["上海松江站","醉白池","松江体育中心","松江新城","松江大学城","洞泾","佘山","泗泾","九亭","中春路","七宝","星中路","合川路","漕河泾开发区","桂林路","宜山路","徐家汇","肇嘉浜路","嘉善路","打浦桥","马当路","陆家浜路","小南门","商城路","世纪大道","杨高中路","芳甸路","蓝天路","台儿庄路","金桥","金吉路","金海路","顾唐路","民雷路","曹路"],
    "11": ["花桥","光明路","兆丰路","安亭","上海汽车城","昌吉东路","上海赛车场","嘉定新城","马陆","陈翔公路","南翔","桃浦新村","武威路","祁连山路","李子园","上海西站","真如","枫桥路","曹杨路","隆德路","江苏路","交通大学","徐家汇","上海游泳馆","龙华","云锦路","龙耀路","东方体育中心","三林",
           "白银路","嘉定西","嘉定北",
           "三林东","浦三路","康恒路","御桥","罗山路","秀沿路","康新公路","迪士尼"],
    "15": ["紫竹高新区","永德路","元江路","双柏路","曙建路","景西路","虹梅南路","景洪路","朱梅路","罗秀路","华东理工大学","上海南站","桂林公园","桂林路","吴中路","姚虹路","红宝石路","娄山关路","长风公园","大渡河路","梅岭北路","铜川路","上海西站","武威东路","古浪路","祁安路","南大路","丰翔路","锦秋路","顾村公园"],
    "17": ["虹桥火车站","国家会展中心","蟠龙路","徐盈路","徐泾北城","嘉松中路","赵巷","汇金路","青浦新城","漕盈路","淀山湖大道","朱家角","东方绿舟","西岑"],
}

for lid, official in OFFICIAL.items():
    detected = []
    for sid, s in data['stations'].items():
        if s['line'] == lid:
            detected.append(s['name_zh'])
    det_set = set(detected)
    off_set = set(official)
    # duplicates
    from collections import Counter
    det_counts = Counter(detected)
    duplicates = [n for n, c in det_counts.items() if c > 1]

    missing = off_set - det_set
    extra = det_set - off_set
    common = off_set & det_set

    print(f"\n=== Line {lid}: detected {len(detected)} / official {len(official)} ===")
    print(f"  Correct names: {len(common)} / {len(official)}")
    if missing:
        print(f"  MISSING ({len(missing)}): {sorted(missing)}")
    if extra:
        print(f"  EXTRA ({len(extra)}): {sorted(extra)}")
    if duplicates:
        print(f"  DUPLICATES: {duplicates}")
