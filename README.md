# taibai_api × Kubernetes 兼容性审计

taibai_api（Kubernetes API 资源模型的 Rust 重写实现）与 Kubernetes v1.34.1 上游 Go 模型的字段级兼容性审计工具与报告。

## 核心产物

- **[audit/REPORT.md](audit/REPORT.md)** — 审计报告（带证据链）：1142 条字段级差异，按 P1-P9 模式分类，含 Go/Rust 两侧源码行号证据、零值序列化实跑对照、影响评估与修复策略（映射到 TEP-0005 policy 代数）
- **[audit/findings_table.json](audit/findings_table.json)** — 机器可读全量差异表（pattern / gv / struct / field / go_wire / rust_wire）
- **[audit/appendix_by_pattern.json](audit/appendix_by_pattern.json)** — 按模式分组的去重清单

## 审计方法（三层证据）

| 层 | 工具 | 产物 |
|---|---|---|
| 静态 tag 比对 | `audit/extract_go.py` + `audit/extract_rust.py`（行状态机解析 Go types.go / Rust pub struct） | `go_types.json` / `rust_types.json` |
| Go 反射零值 ground truth | `audit/gozerogen/`（对每个注册类型 `json.Marshal(reflect.New(t))`） | `go_zero_full.json`（1187 类型 / 65 GV） |
| Rust Default 序列化 | `rust_zero_registry.rs`（`serde_json::to_value(T::default())`） | `rust_zero_full.json`（1131 类型） |

交叉比对：`audit/compare_zero.py` → `classify_scope.py` → 人工复核（报告内全部证据行号）。

## 覆盖范围

- k8s.io/api 60 个版本化 types.go + apiextensions-apiserver 2 + kube-aggregator 2 = **64 个版本化类型源全覆盖**
- 审计范围不含 kubernetes/ 与 taibai_api/ 两棵源码树（本仓库通过 .gitignore 排除，需在本地 clone 后运行工具）

## 复现

```bash
# 1. 静态提取（路径在脚本头部硬编码，指向本地 kubernetes / taibai_api checkout）
python3 audit/extract_go.py
python3 audit/extract_rust.py

# 2. Go 零值 ground truth（go.mod 内 replace 指向本地 kubernetes staging）
cd audit/gozerogen && go run main.go

# 3. Rust 零值（rust_zero_registry.rs 需放入 taibai_api workspace 的临时 crate）

# 4. 交叉比对
python3 audit/compare_zero.py
```
