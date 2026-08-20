#!/usr/bin/env python3
"""解析 Go 命名类型的底层类别，用于精确判定序列化行为"""
import re, json, os, glob

K8S = "/Volumes/mydata/tanghui-home/work/tb_api/kubernetes"
# 收集所有 type 声明
type_decls = {}  # name -> (kind, underlying)

FILES = []
for root, dirs, files in os.walk(f"{K8S}/staging/src/k8s.io/api"):
    if "types.go" in files:
        FILES.append(os.path.join(root, "types.go"))
FILES += [
    f"{K8S}/staging/src/k8s.io/apimachinery/pkg/apis/meta/v1/types.go",
    f"{K8S}/staging/src/k8s.io/apimachinery/pkg/apis/meta/v1/duration.go",
    f"{K8S}/staging/src/k8s.io/apimachinery/pkg/util/intstr/intstr.go",
    f"{K8S}/staging/src/k8s.io/apimachinery/pkg/api/resource/quantity.go",
    f"{K8S}/staging/src/k8s.io/apimachinery/pkg/types/uid.go",
    f"{K8S}/staging/src/k8s.io/apimachinery/pkg/types/namespacedname.go",
    f"{K8S}/staging/src/k8s.io/apimachinery/pkg/apis/meta/v1/group_version.go",
    f"{K8S}/staging/src/k8s.io/apiextensions-apiserver/pkg/apis/apiextensions/v1/types.go",
    f"{K8S}/staging/src/k8s.io/kube-aggregator/pkg/apis/apiregistration/v1/types.go",
]

for path in FILES:
    text = open(path, encoding='utf-8').read()
    for m in re.finditer(r'^type (\w+) (struct \{|string|int32|int64|uint32|uint64|float32|float64|bool|int|uint|\[\]|\w+)', text, re.M):
        name, rest = m.group(1), m.group(2)
        if rest.startswith('struct'):
            kind = 'struct'
        elif rest in ('string','int32','int64','uint32','uint64','float32','float64','bool','int','uint'):
            kind = rest
        elif rest.startswith('[]'):
            kind = 'slice'
        elif rest.startswith('map'):
            kind = 'map'
        else:
            kind = f'alias:{rest}'
        # map 类型的完整声明
        m2 = re.search(rf'^type {name} (map\[[^\]]+\][^\n]+)', text, re.M)
        if m2:
            kind = 'map'
        type_decls.setdefault(name, kind)

# 手工补充跨包关键类型
manual = {
    'metav1.Time': 'struct_time', 'resource.Quantity': 'struct_quantity',
    'intstr.IntOrString': 'struct_intorstring', 'types.UID': 'string',
    'metav1.Duration': 'struct_duration', 'metav1.LabelSelector': 'struct',
    'Time': 'struct_time', 'Quantity': 'struct_quantity', 'IntOrString': 'struct_intorstring',
    'UID': 'string',
}
json.dump({"decls": type_decls, "manual": manual}, open("/Volumes/mydata/tanghui-home/work/tb_api/audit/go_type_kinds.json","w"), indent=1)
print(f"解析 {len(type_decls)} 个命名类型")
# 打印一些样本
for n in ['TaintEffect','ResourceList','ConditionStatus','ServiceType','LimitResponseType','Protocol','PullPolicy','DNSPolicy','FieldError']:
    print(f"  {n}: {type_decls.get(n)}")
