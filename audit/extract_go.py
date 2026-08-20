#!/usr/bin/env python3
"""提取 k8s Go types.go 的结构体字段 + json/protobuf tag 信息。
输出 JSON：{ "GroupVersion": { "StructName": [ {field...} ] } }
"""
import re, json, sys, os

GO_DIR = "/Volumes/mydata/tanghui-home/work/tb_api/kubernetes/staging/src/k8s.io"
EXTRA = [
    ("/Volumes/mydata/tanghui-home/work/tb_api/kubernetes/staging/src/k8s.io/apimachinery/pkg/apis/meta/v1/types.go", "meta/v1"),
    ("/Volumes/mydata/tanghui-home/work/tb_api/kubernetes/staging/src/k8s.io/apimachinery/pkg/util/intstr/intstr.go", "intstr"),
    ("/Volumes/mydata/tanghui-home/work/tb_api/kubernetes/staging/src/k8s.io/apimachinery/pkg/api/resource/quantity.go", "resource-quantity"),
    ("/Volumes/mydata/tanghui-home/work/tb_api/kubernetes/staging/src/k8s.io/apimachinery/pkg/runtime/types.go", "runtime"),
    ("/Volumes/mydata/tanghui-home/work/tb_api/kubernetes/staging/src/k8s.io/apimachinery/pkg/apis/meta/v1/duration.go", "meta/v1"),
    ("/Volumes/mydata/tanghui-home/work/tb_api/kubernetes/staging/src/k8s.io/apiextensions-apiserver/pkg/apis/apiextensions/v1/types.go", "apiextensions/v1"),
    ("/Volumes/mydata/tanghui-home/work/tb_api/kubernetes/staging/src/k8s.io/apiextensions-apiserver/pkg/apis/apiextensions/v1beta1/types.go", "apiextensions/v1beta1"),
    ("/Volumes/mydata/tanghui-home/work/tb_api/kubernetes/staging/src/k8s.io/kube-aggregator/pkg/apis/apiregistration/v1/types.go", "apiregistration/v1"),
    ("/Volumes/mydata/tanghui-home/work/tb_api/kubernetes/staging/src/k8s.io/kube-aggregator/pkg/apis/apiregistration/v1beta1/types.go", "apiregistration/v1beta1"),
]

# 匹配: Name Type `json:"...,omitempty" protobuf:"..."`  （跨行 struct 字段）
FIELD_RE = re.compile(
    r'^\t(?P<name>[A-Z][A-Za-z0-9_]*)\s+'
    r'(?P<type>.*?)'
    r'`(?P<tags>[^`]*)`?\s*$'
)

def parse_tags(tagstr):
    tags = {}
    for m in re.finditer(r'(\w+):"([^"]*)"', tagstr or ""):
        tags[m.group(1)] = m.group(2)
    return tags

def parse_file(path, gv):
    out = {}
    lines = open(path, encoding='utf-8').read().split('\n')
    i = 0
    while i < len(lines):
        line = lines[i]
        m = re.match(r'^type (\w+) struct \{', line)
        if m:
            sname = m.group(1)
            fields = []
            i += 1
            buf = ""
            while i < len(lines) and not lines[i].startswith('}'):
                raw = lines[i]
                if raw.strip().startswith('//') or not raw.strip():
                    i += 1; continue
                buf += raw + "\n"
                # 字段以反引号 tag 结束，或者下一个非注释行开始
                if '`' in raw or (raw.strip().endswith(';')):
                    fm = re.match(r'\t(\w+)\s+(.*?)`([^`]*)`', buf)
                    if not fm:
                        fm = re.match(r'\t(\w+)\s+([^`\s]+)\s*$', buf.strip('\n'))
                    if fm:
                        fields.append({
                            "name": fm.group(1),
                            "type": fm.group(2).strip().replace('\n',' '),
                            "tags": parse_tags(fm.group(3) if fm.lastindex and fm.lastindex >= 3 else ""),
                        })
                    buf = ""
                i += 1
            out[sname] = fields
        i += 1
    return out

result = {}
for root, dirs, files in os.walk(os.path.join(GO_DIR, "api")):
    if "types.go" in files and "/v" in root.replace(GO_DIR, ""):
        rel = root.replace(GO_DIR + "/api/", "")
        result[rel] = parse_file(os.path.join(root, "types.go"), rel)

for path, gv in EXTRA:
    if os.path.exists(path):
        d = parse_file(path, gv)
        if gv in result:
            result[gv].update(d)
        else:
            result[gv] = d

json.dump(result, open("/Volumes/mydata/tanghui-home/work/tb_api/audit/go_types.json", "w"), indent=1)
total = sum(len(v) for v in result.values())
print(f"解析完成: {len(result)} 个组版本, {total} 个结构体")
for gv in sorted(result):
    print(f"  {gv}: {len(result[gv])} structs")
