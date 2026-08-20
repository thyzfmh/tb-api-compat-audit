#!/usr/bin/env python3
"""核心对比器: Go json tag 语义 vs Rust serde 行为。

Go json 序列化规则 (encoding/json + k8s 惯例):
- `json:"name"`           -> 值类型 T: 零值也会输出 (string -> "", int -> 0, bool -> false)
- `json:"name,omitempty"` -> 零值省略 (string ""省略, int 0省略, bool false省略, slice/map nil省略)
- `json:"name"` + *T      -> 指针: nil 省略? 不! 无 omitempty 的指针 nil 会输出 null
- `json:"name,omitempty"` + *T -> nil 省略
- struct 值类型 + omitempty -> Go encoding/json 不省略 struct 零值 (除非 omitzero Go1.24)
- slice/map + omitempty -> nil/空 省略
"""
import json, re, sys

go = json.load(open('/Volumes/mydata/tanghui-home/work/tb_api/audit/go_types.json'))
rust = json.load(open('/Volumes/mydata/tanghui-home/work/tb_api/audit/rust_types.json'))

# Go 字段名 -> Rust snake_case
# Rust 字段名无法从 Go 字段名机械推导的情况映射表
RUST_NAME_FIXUPS = {
    # Go 名 -> Rust 名（处理缩写词、关键字）
}

def go_to_rust(name):
    s = re.sub(r'(.)([A-Z][a-z]+)', r'\1_\2', name)
    s = re.sub(r'([a-z0-9])([A-Z])', r'\1_\2', s)
    s = s.lower()
    # 修正常见缩写词: i_ps -> ips, i_ds -> ids, u_r_ls...
    s = re.sub(r'i_p_s\b', 'ips', s)
    s = re.sub(r'i_ds\b', 'ids', s)
    s = re.sub(r'u_r_ls\b', 'urls', s)
    s = re.sub(r'a_p_is\b', 'apis', s)
    s = re.sub(r'c_p_us\b', 'cpus', s)
    s = re.sub(r'u_i_ds\b', 'uids', s)
    s = re.sub(r'u_r_ls\b', 'urls', s)
    # 缩写词尾缀修正: ww_ns -> wwns
    s = re.sub(r'ww_ns\b', 'wwns', s)
    if s == 'type': return 'r#type'
    return s

def go_json_name(tags):
    j = tags.get('json', '')
    if not j: return None, {}
    parts = j.split(',')
    name = parts[0]
    opts = set(parts[1:])
    return name, opts

def analyze_go_field(fname, ftype, tags):
    """返回 (json_name, omit_empty, is_pointer, is_value_string, is_value_int, is_value_bool, go_base_type)"""
    jname, opts = go_json_name(tags)
    if jname is None: return None
    omit = 'omitempty' in opts
    omitzero = 'omitzero' in opts
    is_ptr = ftype.startswith('*')
    base = ftype.lstrip('*').strip()
    return {
        "json_name": jname,
        "omitempty": omit,
        "omitzero": omitzero,
        "is_ptr": is_ptr,
        "go_type": base,
    }

# ============ Rust 侧: 分析 serde 行为 ============
def rust_json_name(field, struct_attrs):
    """从 serde attrs 中提取 json 名与策略"""
    attrs = field['attrs']
    rname = None
    for a in attrs:
        m = re.search(r'rename\s*=\s*"([^"]+)"', a)
        if m:
            rname = m.group(1)
            break
    if rname: return rname
    # camelCase 规则: snake_case -> camelCase
    parts = field['name'].split('_')
    return parts[0] + ''.join(p.capitalize() for p in parts[1:])

def rust_skip_policy(field):
    """返回 'none'|'is_none'|'string_empty'|'vec_empty'|'map_empty'|'is_false'|'struct_omit'|'scalar_omit'|..."""
    for a in field['attrs']:
        m = re.search(r'skip_serializing_if\s*=\s*"([^"]+)"', a)
        if m:
            s = m.group(1)
            if 'is_none_or_zero_i32' in s or 'is_none_or_zero_i64' in s: return 'scalar_omit'
            if 'value_struct_omit' in s and 'zero' not in s: return 'struct_omit'
            if 'is_none_or_zero_timestamp' in s: return 'timestamp_omitzero'
            if 'Option::is_none' in s: return 'is_none'
            if 'String::is_empty' in s: return 'string_empty'
            if 'Vec::is_empty' in s: return 'vec_empty'
            if 'BTreeMap::is_empty' in s or 'HashMap::is_empty' in s or 'Map::is_empty' in s: return 'map_empty'
            if 'is_false' in s: return 'is_false'
            if 'is_zero' in s: return 'scalar_omit'
            return f'other:{s}'
    # with = value_struct_omit (无 skip_serializing_if): 始终序列化, None->default
    for a in field['attrs']:
        if 'with = "crate::common::json_shape::value_struct_omit"' in a:
            return 'struct_omit'
        if 'with = "crate::common::json_shape::value_scalar_omit"' in a:
            return 'scalar_omit_with'
    return 'none'

def rust_type_shape(field):
    t = field['rust_type']
    is_opt = t.startswith('Option<')
    inner = t[7:-1].strip() if is_opt else t
    kind = 'other'
    if inner.startswith('Vec<'): kind = 'vec'
    elif inner.startswith('BTreeMap<') or inner.startswith('HashMap<'): kind = 'map'
    elif inner == 'String': kind = 'string'
    elif inner in ('i32','i64','u32','u16','u8','usize','f32','f64'): kind = 'num'
    elif inner == 'bool': kind = 'bool'
    else: kind = 'struct'
    return is_opt, kind, inner

# ============ 对比 ============
findings = []

def check_compat(go_b, rust_b, g_base, r_kind, g_ptr, r_opt):
    # Go always_emit_zero (值类型无 omitempty) 期望: 始终输出字段（零值形式）
    if go_b == 'always_emit_zero':
        # Rust 必须始终输出 (always_emit 或 emit_default_struct)
        return rust_b in ('always_emit', 'emit_default_struct', 'emit_always')
    if go_b == 'emit_null_when_nil':
        # Go: nil 指针输出 null; 期望 Rust Option None -> null
        return rust_b in ('emit_null_when_none', 'emit_default_struct')
    if go_b == 'omit_zero_scalar':
        if g_base.startswith('map') or g_base.startswith('[]'):
            return rust_b == 'skip_when_empty'
        # Go 值 struct + omitempty: struct 不省略! 但 Go 值 string/int/bool 零值省略
        if g_base in ('string','int','int32','int64','uint32','bool','float32','float64'):
            return rust_b == 'skip_when_zero_or_none' or rust_b == 'skip_when_empty' or rust_b == 'skip_when_false'
        # struct 值类型
        return rust_b == 'emit_default_struct'
    if go_b == 'omit_nil':
        return rust_b in ('skip_when_none', 'skip_when_none_or_empty', 'skip_when_zero_or_none', 'emit_default_struct', 'skip_when_empty', 'skip_when_false')
    return True


def add(gv, sname, severity, category, detail, go_file=None, rust_file=None, lines=None):
    findings.append({
        "gv": gv, "struct": sname, "severity": severity, "category": category, "detail": detail,
    })

# 对每个组版本的每个 Go struct
for gv, structs in go.items():
    r_gv = gv  # taibai 同名 gv
    if r_gv not in rust:
        # common 映射
        continue
    r_structs = rust[r_gv]
    for sname, fields in structs.items():
        if sname not in r_structs:
            continue  # 缺 struct 已单独统计
        rs = r_structs[sname]
        r_fields = {f['name']: f for f in rs['fields']}
        for gf in fields:
            gof = analyze_go_field(gf['name'], gf['type'], gf['tags'])
            if gof is None: continue
            jname = gof["json_name"]
            # 找对应 Rust 字段
            rf = r_fields.get(go_to_rust(gf['name']))
            if rf is None:
                # 尝试直接同名
                rf = r_fields.get(gf['name'])
            if rf is None:
                add(gv, sname, "HIGH", "missing_field", f"Go field {gf['name']} ({gof['go_type']}) missing in Rust")
                continue
            # ---- 1. JSON 名对比 ----
            rjname = rust_json_name(rf, rs['attrs'])
            if rjname != jname:
                add(gv, sname, "HIGH", "json_name", f"field {gf['name']}: Go json name '{jname}' != Rust '{rjname}'")
            # ---- 2. 序列化策略对比 ----
            g_omit = gof["omitempty"]
            g_ptr = gof["is_ptr"]
            g_base = gof["go_type"]
            # Go 行为分类
            # value scalar no omitempty: 零值输出
            if not g_omit and not g_ptr:
                go_behavior = 'always_emit_zero'   # "", 0, false 都输出
            elif not g_omit and g_ptr:
                go_behavior = 'emit_null_when_nil' # nil -> "field": null
            elif g_omit and not g_ptr:
                go_behavior = 'omit_zero_scalar'   # 零值省略 (struct 值类型不省略!)
            else:
                go_behavior = 'omit_nil'           # 指针 nil 省略
            policy = rust_skip_policy(rf)
            is_opt, kind, inner = rust_type_shape(rf)
            # Rust 行为
            if policy in ('is_none',) and is_opt:
                rust_behavior = 'skip_when_none'
            elif policy == 'struct_omit':
                rust_behavior = 'emit_default_struct'
            elif policy == 'scalar_omit':
                rust_behavior = 'skip_when_zero_or_none'
            elif policy == 'scalar_omit_with':
                rust_behavior = 'emit_always'  # with only
            elif policy == 'timestamp_omitzero':
                rust_behavior = 'omit_when_zero_timestamp'
            elif policy == 'none' and is_opt:
                rust_behavior = 'emit_null_when_none'
            elif policy == 'none' and not is_opt:
                rust_behavior = 'always_emit'
            elif policy == 'string_empty' and kind=='string' and not is_opt:
                rust_behavior = 'skip_when_empty'
            elif policy == 'string_empty' and kind=='string' and is_opt:
                rust_behavior = 'skip_when_none_or_empty'
            elif policy == 'vec_empty':
                rust_behavior = 'skip_when_empty'
            elif policy == 'map_empty':
                rust_behavior = 'skip_when_empty'
            elif policy == 'is_false':
                rust_behavior = 'skip_when_false'
            elif policy.startswith('other:'):
                rust_behavior = policy
            else:
                rust_behavior = f'?{policy}/{is_opt}/{kind}'
            # 判定是否一致
            compat = check_compat(go_behavior, rust_behavior, g_base, kind, g_ptr, is_opt)
            if not compat:
                add(gv, sname, "HIGH", "serde_policy", f"field {gf['name']}: Go({gof['go_type']}{' omitempty' if g_omit else ''}): {go_behavior} vs Rust({rf['rust_type']}, {policy}): {rust_behavior}")


json.dump(findings, open('/Volumes/mydata/tanghui-home/work/tb_api/audit/findings_stage1.json','w'), indent=1)
print(f"stage1 findings: {len(findings)}")
from collections import Counter
print(Counter([f['category'] for f in findings]))
