#!/usr/bin/env python3
"""对比器 v2: 以 Go 零值 marshal 实测 + 类型别名解析为基础的精确对比"""
import json, re, sys
from collections import defaultdict

go_types = json.load(open('go_types.json'))
rust_types = json.load(open('rust_types.json'))
go_kinds = json.load(open('go_type_kinds.json'))['decls']
go_zero = json.load(open('go_zero_full.json'))

def go_to_rust(name):
    s = re.sub(r'(.)([A-Z][a-z]+)', r'\1_\2', name)
    s = re.sub(r'([a-z0-9])([A-Z])', r'\1_\2', s)
    s = s.lower()
    s = re.sub(r'i_p_s\b', 'ips', s)
    s = re.sub(r'i_ds\b', 'ids', s)
    s = re.sub(r'u_r_ls\b', 'urls', s)
    s = re.sub(r'ww_ns\b', 'wwns', s)
    s = re.sub(r'u_i_ds\b', 'uids', s)
    if s == 'type': return 'r#type'
    return s

def find_go_zero(gv, sname):
    """在 go_zero_full.json 中找到对应类型（类型名带包前缀）"""
    group = gv.split('/')[0]
    # 包前缀规则: core/v1 -> v1; apps/v1 -> v1 (会重复!), 需要多候选
    candidates = []
    for t in go_zero:
        if t.endswith('.' + sname):
            candidates.append(t)
    # 匹配 group: "v1.NodeSystemInfo" 匹配 core; "v1.PodSpec" 也匹配 apps 的 PodSpec? apps 没有 PodSpec
    # 精确: 通过 go_types 的 gv 找不到包名，只能用启发式
    return candidates

def analyze(field):
    """Rust 侧 wire 行为分析"""
    attrs = ' '.join(field.get('attrs') or [])
    rt = field['rust_type']
    is_opt = rt.startswith('Option<')
    inner = rt[7:-1].strip() if is_opt else rt
    skip = None
    m = re.search(r'skip_serializing_if\s*=\s*"([^"]+)"', attrs)
    if m:
        skip = m.group(1)
    has_with = 'with = "crate::common::json_shape::value_struct_omit"' in attrs
    has_with_zero = 'value_struct_omit_zero' in attrs
    rename = None
    m = re.search(r'rename\s*=\s*"([^"]+)"', attrs)
    if m:
        rename = m.group(1)
    # flatten?
    flatten = 'flatten' in attrs
    return {'skip': skip, 'is_opt': is_opt, 'inner': inner, 'rename': rename,
            'has_with': has_with, 'has_with_zero': has_with_zero, 'flatten': flatten, 'attrs': attrs}

def rust_wire_behavior(field):
    """Rust 字段在默认值状态下的 wire 行为（None/空/0...）"""
    a = analyze(field)
    rt = field['rust_type']
    # 展开基础类型
    inner = a['inner']
    skip = a['skip']
    if a['flatten']:
        return 'flatten'
    # with = value_struct_omit: None 序列化为默认 struct（字段仍在）
    if a['has_with']:
        return 'emit_default_struct'
    if skip and 'is_none_or_zero' in skip:
        return 'skip_if_none_or_zero'
    if skip and 'Option::is_none' in skip:
        if a['is_opt']:
            return 'skip_when_none'
        # 非 Option 却用 is_none 不可能
        return 'skip_when_none'
    if skip and 'String::is_empty' in skip:
        return 'skip_when_empty_str' if not a['is_opt'] else 'skip_when_none_or_empty'
    if skip and 'Vec::is_empty' in skip:
        return 'skip_when_empty_vec'
    if skip and ('BTreeMap::is_empty' in skip or 'HashMap::is_empty' in skip):
        return 'skip_when_empty_map'
    if skip and 'is_false' in skip:
        return 'skip_when_false'
    if skip:
        return f'other_skip:{skip}'
    # 无 skip
    if a['is_opt']:
        return 'emit_null_when_none'
    return 'emit_always'

def kind_of_rust(rt):
    if rt.startswith('Vec<'): return 'vec'
    if rt.startswith('BTreeMap<') or rt.startswith('HashMap<'): return 'map'
    if rt == 'String': return 'string'
    if rt in ('i32','i64','u32','f64','f32'): return 'num'
    if rt == 'bool': return 'bool'
    return 'struct'

# ============ 主对比逻辑 ============
findings = []
inline_records = defaultdict(list)  # (gv, struct) -> inline 展开的 Go 字段（供缺失字段记录）
go_inline_map = {}  # (gv, sname) -> Go 的 inline 字段（匿名嵌入）

# 预处理: 找到所有 Go inline 嵌入
for gv, structs in go_types.items():
    for sname, fields in structs.items():
        for f in fields:
            if f['name'] and f['type'] and not f['type'].startswith('*') and f['type'] in go_types.get(gv, {}) and f['tags'].get('json','').startswith(','):
                # 匿名嵌入同包类型 (json:",inline")
                go_inline_map.setdefault((gv, sname), []).append(f['type'])

def expand_go_fields(gv, sname, seen=None):
    """展开 Go struct 的 inline 嵌入字段"""
    if seen is None: seen = set()
    if (gv, sname) in seen: return []
    seen.add((gv, sname))
    result = []
    fields = go_types.get(gv, {}).get(sname, [])
    inlines = go_inline_map.get((gv, sname), [])
    for f in fields:
        # inline 嵌入字段本身跳过（其字段被展开）
        if f['type'] in inlines and f['tags'].get('json','').startswith(','):
            result.extend(expand_go_fields(gv, f['type'], seen))
        else:
            result.append(f)
    return result

for gv, structs in go_types.items():
    r_gv = gv
    if r_gv not in rust_types:
        continue
    r_structs = rust_types[r_gv]
    for sname, fields in structs.items():
        if sname not in r_structs:
            continue
        rs = r_structs[sname]
        r_fields = {f['name']: f for f in rs['fields']}
        go_fields_expanded = expand_go_fields(gv, sname)
        for gf in go_fields_expanded:
            if not gf.get('tags'): continue
            jtag = gf['tags'].get('json', '')
            if jtag in ('-', ''): continue
            parts = jtag.split(',')
            jname = parts[0]
            omit = 'omitempty' in parts[1:]
            gtype = gf['type']
            is_ptr = gtype.startswith('*')
            base = gtype.lstrip('*').strip()
            short = base.split('.')[-1]
            # Go 类型类别
            if short in ('string','bool','int','int32','int64','uint32','uint64','float32','float64'):
                gkind = 'scalar'
            elif short.startswith('[]'):
                gkind = 'slice'
            elif short.startswith('map'):
                gkind = 'map'
            else:
                k = go_kinds.get(short)
                if k in ('string','bool','int32','int64','uint32','float64','int'):
                    gkind = 'scalar_alias'
                elif k == 'map': gkind = 'map'
                elif k == 'slice': gkind = 'slice'
                elif k and k.startswith('alias:'):
                    b = k[6:].split('.')[-1]
                    gkind = 'scalar_alias' if b in ('string','bool','int32','int64') else 'struct'
                else: gkind = 'struct'
            # Go 零值 wire 行为
            if not omit:
                if is_ptr or gkind in ('slice','map'):
                    go_wire = 'null'          # nil -> null
                elif gkind in ('scalar','scalar_alias'):
                    go_wire = 'zero_literal'  # "" / 0 / false
                else:
                    go_wire = 'present_full'  # struct 值
            else:
                if gkind == 'struct' and not is_ptr:
                    go_wire = 'present_full'  # struct 值 + omitempty 仍输出!
                else:
                    go_wire = 'absent'
            # 找 Rust 字段
            rf = r_fields.get(go_to_rust(gf['name']))
            if rf is None:
                rf = r_fields.get(gf['name'])
            if rf is None:
                # type_ / r#type 变体
                for cand in (go_to_rust(gf['name'])+'_', go_to_rust(gf['name']).replace('r#','type_')):
                    if cand in r_fields:
                        rf = r_fields[cand]; break
            if rf is None:
                findings.append({"gv": gv, "struct": sname, "category": "missing_field",
                    "go_field": gf['name'], "go_type": gtype, "json_name": jname, "go_wire": go_wire,
                    "detail": f"Go field {gf['name']} ({gtype}) 无对应 Rust 字段"})
                continue
            rust_wire = rust_wire_behavior(rf)
            # 兼容性矩阵: go_wire -> 可接受的 rust_wire
            ACCEPT = {
                'null':           {'emit_null_when_none'},  # Go 无 omitempty ptr/slice/map: nil -> null
                'zero_literal':   {'emit_always', 'emit_default_struct'},
                'present_full':   {'emit_always', 'emit_default_struct'},
                'absent':         {'skip_when_none', 'skip_when_empty_str', 'skip_when_none_or_empty',
                                   'skip_when_empty_vec', 'skip_when_empty_map', 'skip_when_false',
                                   'skip_if_none_or_zero', 'emit_default_struct', 'emit_null_when_none'},
            }
            ok = rust_wire in ACCEPT.get(go_wire, set())
            if not ok:
                # json 名也要检查
                a = analyze(rf)
                rjname = a['rename'] or None
                findings.append({"gv": gv, "struct": sname, "category": "serde_policy",
                    "go_field": gf['name'], "go_type": gtype, "json_name": jname,
                    "go_wire": go_wire, "rust_wire": rust_wire,
                    "rust_type": rf['rust_type'], "rust_path": rs['path'],
                    "detail": f"Go({gtype}{' omitempty' if omit else ''}) 零值={go_wire}; Rust({rf['rust_type']}) 行为={rust_wire}"})
            # json name 校验
            if rf:
                a = analyze(rf)
                # rename 优先; 否则 camelCase 推导
                if a['rename']:
                    actual_name = a['rename']
                else:
                    parts2 = rf['name'].split('_')
                    actual_name = parts2[0] + ''.join(p.capitalize() for p in parts2[1:])
                    # r#type -> type
                    actual_name = actual_name.replace('r#','')
                if actual_name != jname:
                    findings.append({"gv": gv, "struct": sname, "category": "json_name",
                        "go_field": gf['name'], "json_name": jname, "rust_json_name": actual_name,
                        "rust_path": rs['path'],
                        "detail": f"JSON 名不一致: Go='{jname}' Rust='{actual_name}'"})

json.dump(findings, open('findings_stage2.json','w'), indent=1)
from collections import Counter
print(f"stage2 findings: {len(findings)}")
print(Counter([f['category'] for f in findings]))
