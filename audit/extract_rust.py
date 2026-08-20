#!/usr/bin/env python3
"""v3: 行状态机提取，正确关联字段属性"""
import re, json, os

SRC = "/Volumes/mydata/tanghui-home/work/tb_api/taibai_api/src"

def gv_of(rel):
    parts = rel.split(os.sep)
    if len(parts) >= 2 and re.match(r'^v\d+(alpha|beta)?\d*$', parts[1]):
        return parts[0] + "/" + parts[1]
    return parts[0]

STRUCT_RE = re.compile(r'^pub(?:\(crate\))? struct (\w+)')
FIELD_RE = re.compile(r'^\s*pub (r#\w+|\w+):\s*(.*)$')
ATTR_START = re.compile(r'^\s*#\[')

def parse_rust_file(path):
    text = open(path, encoding='utf-8').read()
    lines = text.split('\n')
    structs = {}
    i = 0
    struct_attrs = []
    while i < len(lines):
        line = lines[i]
        m = STRUCT_RE.match(line)
        if m:
            sname = m.group(1)
            # struct body: 直到 depth 归零
            j = i + 1
            depth = lines[i].count('{') - lines[i].count('}')
            started = '{' in lines[i]
            fields = []
            pending_attrs = []
            pending_type = None
            while j < len(lines):
                l = lines[j]
                # strip doc/comment lines so braces like "({})" in docs don't skew depth
                stripped = l.strip()
                is_comment = stripped.startswith('//') or stripped.startswith('/*') or stripped.startswith('*')
                if not is_comment:
                    code_part = l.split('//')[0]
                    depth += code_part.count('{') - code_part.count('}')
                    if '{' in code_part:
                        started = True
                if started and depth <= 0:
                    break
                ls = l.strip()
                # 属性行（可能多行 #[serde( ... )]）
                if ls.startswith('#['):
                    # 累积整个属性直到括号配对
                    attr = l
                    k = j
                    while attr.count('[') > attr.count(']') and k+1 < len(lines):
                        k += 1
                        attr += ' ' + lines[k].strip()
                    pending_attrs.append(re.sub(r'\s+', ' ', attr))
                    j = k + 1
                    continue
                fm = FIELD_RE.match(l)
                if fm:
                    fname = fm.group(1)
                    ftype = fm.group(2)
                    # 类型可能跨行（直到行尾逗号或 ;）
                    k = j
                    while not (ftype.rstrip().endswith(',') or ftype.rstrip().endswith(';')) and k+1 < len(lines):
                        k += 1
                        ftype += ' ' + lines[k].strip()
                        if lines[k].strip().startswith('#') or lines[k].strip().startswith('pub'):
                            break
                    # 清理类型尾部
                    ftype = ftype.split('//')[0].split('///')[0]
                    ftype = ' '.join(ftype.split()).rstrip(',;').strip()
                    fields.append({
                        "name": fname,
                        "rust_type": ftype,
                        "attrs": pending_attrs,
                    })
                    pending_attrs = []
                    j = k + 1
                    continue
                # 注释/空行不重置 attrs；其他代码行重置
                if ls and not ls.startswith('//'):
                    pending_attrs = []
                j += 1
            structs[sname] = {"path": path.replace(SRC+"/",""), "line": i+1, "attrs": struct_attrs, "fields": fields}
            struct_attrs = []
            i = j
            continue
        if ATTR_START.match(line):
            attr = line
            k = i
            while attr.count('[') > attr.count(']') and k+1 < len(lines):
                k += 1
                attr += ' ' + lines[k].strip()
            struct_attrs.append(re.sub(r'\s+', ' ', attr))
            i = k + 1
            continue
        if line.strip() and not line.strip().startswith('//'):
            struct_attrs = []
        i += 1
    return structs

result = {}
for root, dirs, files in os.walk(SRC):
    rel = os.path.relpath(root, SRC)
    parts = rel.split(os.sep)
    # 仅跳过段名精确等于/常见测试目录名的段
    SKIP_SEGMENTS = {"test", "tests", "internal", "conversion", "conversion_roundtrip", "serde_roundtrip", "roundtrip", "bin", "test_fixtures", "test_utils"}
    if rel.startswith('.') or any(p in SKIP_SEGMENTS for p in parts):
        continue
    for fn in files:
        if not fn.endswith(".rs") or fn.endswith(".backup"):
            continue
        p = os.path.join(root, fn)
        d = parse_rust_file(p)
        if d:
            gv = gv_of(rel)
            result.setdefault(gv, {}).update({k: {**v, "gv": gv} for k,v in d.items()})

json.dump(result, open("/Volumes/mydata/tanghui-home/work/tb_api/audit/rust_types.json","w"), indent=1)
total = sum(len(v) for v in result.values())
print(f"OK: {len(result)} groups, {total} structs")
ni = result['core/v1']['NodeSystemInfo']
for f in ni['fields']:
    print(f['name'], '|', f['rust_type'], '|', f['attrs'])
