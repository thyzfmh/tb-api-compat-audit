#!/usr/bin/env python3
"""Go vs Rust 零值序列化全字段级 diff —— 最强证据层"""
import json, re
from collections import defaultdict

go_zero = json.load(open('go_zero_full.json'))
rust_zero = json.load(open('rust_zero_full.json'))

findings = []

def diff_json(gv, sname, go_obj, rust_obj):
    """对比两个零值 JSON 对象的顶层字段差异"""
    go_fields = set(go_obj.keys()) if isinstance(go_obj, dict) else set()
    rust_fields = set(rust_obj.keys()) if isinstance(rust_obj, dict) else set()
    for f in go_fields - rust_fields:
        v = go_obj[f]
        findings.append({
            "gv": gv, "struct": sname, "field": f,
            "category": "zero_value_missing_field",
            "go_shape": describe(v), "rust_shape": "<absent>",
            "detail": f"Go 零值输出 '{f}': {describe(v)}; Rust 缺失该字段",
        })
    for f in rust_fields - go_fields:
        v = rust_obj[f]
        findings.append({
            "gv": gv, "struct": sname, "field": f,
            "category": "zero_value_extra_field",
            "go_shape": "<absent>", "rust_shape": describe(v),
            "detail": f"Go 零值不输出 '{f}'; Rust 输出 {describe(v)}",
        })
    for f in go_fields & rust_fields:
        gv_v, rv_v = go_obj[f], rust_obj[f]
        if json.dumps(gv_v, sort_keys=True) != json.dumps(rv_v, sort_keys=True):
            findings.append({
                "gv": gv, "struct": sname, "field": f,
                "category": "zero_value_value_mismatch",
                "go_shape": describe(gv_v), "rust_shape": describe(rv_v),
                "detail": f"'{f}': Go={describe(gv_v)} vs Rust={describe(rv_v)}",
            })

def describe(v):
    s = json.dumps(v, sort_keys=True)
    if len(s) > 60: s = s[:57] + '...'
    return s

# 类型对齐
matched = 0
go_keys = set(go_zero.keys())
rust_keys = set(rust_zero.keys())
for key in sorted(go_keys & rust_keys):
    go_obj = json.loads(go_zero[key]['zeroMarshal']) if not go_zero[key]['zeroMarshal'].startswith('ERR') else None
    if go_obj is None: continue
    rust_obj = rust_zero[key]
    if isinstance(rust_obj, str) and rust_obj.startswith('__SERIALIZE_ERROR__'): continue
    # Go 是 ptr marshal: {"name":""} ; Rust 直接对象
    diff_json(key.split('::')[0], key.split('::')[1], go_obj, rust_obj)
    matched += 1

# Go 有 Rust 没有的类型
for key in sorted(go_keys - rust_keys):
    findings.append({"gv": key.split('::')[0], "struct": key.split('::')[1], "field": None,
        "category": "missing_type", "go_shape": None, "rust_shape": None,
        "detail": f"Rust 缺少类型 {key}"})
for key in sorted(rust_keys - go_keys):
    findings.append({"gv": key.split('::')[0], "struct": key.split('::')[1], "field": None,
        "category": "extra_type", "go_shape": None, "rust_shape": None,
        "detail": f"Rust 多出类型 {key}（可能是内部实现类型）"})

json.dump(findings, open('findings_zero.json','w'), indent=1)
from collections import Counter
print(f"匹配类型数: {matched}")
print(f"零值序列化差异发现: {len(findings)}")
print(Counter([f['category'] for f in findings]))
