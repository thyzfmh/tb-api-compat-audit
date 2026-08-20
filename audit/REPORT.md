# taibai_api × Kubernetes v1.34.1 模型兼容性审计报告（带证据版）

**审计日期**：2026-08-20
**基线**：taibai_api（当前工作区）× kubernetes v1.34.1（`git describe --tags` 验证 = v1.34.1）
**范围**：业务代码（`taibai_api/src/`），不含测试代码
**比对维度**：字段名（JSON wire name）、字段覆盖（结构）、零值序列化形态、默认值行为

> **证据标注约定**：
> - `Go:` 指 `kubernetes/staging/src/k8s.io/api/.../types.go` 的行号与原始代码（可直接点击跳转核对）
> - `Rust:` 指 `taibai_api/src/...` 的行号与原始代码
> - `Go零值:` / `Rust零值:` 指反射/serde 实跑产物（`audit/go_zero_full.json`、`audit/rust_zero_full.json`）
> - `实跑:` 指在 taibai_api 下创建临时 integration test 实际运行得到的输出

---

## 1. 执行摘要

| 指标 | 数值 |
|---|---:|
| Go 侧解析 struct（68 个 group-version 源） | 1191 |
| Rust 侧解析 struct（67 个分组） | 1149 |
| 同名配对 | 1090 |
| Go 反射零值 ground truth 类型数（65 个 GV） | **1187**（含 apiextensions/apiregistration 补全） |
| Rust Default 序列化类型数 | 1131 |
| **字段级差异总数** | **1142**（632 类型 / 64 GV） |
| JSON 字段名错误（数据丢失级） | 8 |
| 结构性缺失字段（数据丢失级） | 34 |
| 未实现 / scope 外类型 | 47 |

严重度分层：

| 级别 | 内容 | 数量 |
|---|---|---:|
| **S0 数据丢失** | JSON 名错误（§5，实跑验证） | 8 |
| **S0 数据丢失** | 结构性缺失字段（§4.10） | 34 |
| **S1 缺输出** | Go 值 struct 字段总输出 vs Rust skip（P1） | 452 |
| **S2 零值形态** | null/`""`/`0`/`[]` vs 缺席（P8/P4/P9/P1b/P3/P4b/P2/P7） | 633 |
| **S3 状态污染** | Rust 泄漏 Go 没有的默认值（P6/P5） | 57 |
| **S4 范围决策** | 未实现类型（§6） | 47 类型 |

**核心结论**：差异不是零散 bug，而是系统性序列化策略缺口——taibai 用 `Option<T>` + `skip_serializing_if` 建模了 Go 的**值类型字段**与**无 omitempty 指针/切片字段**。修复代数（TEP-0005）已在代码库就绪（[json_shape.rs](taibai_api/src/common/json_shape.rs)），样板即 `kubeProxyVersion` 曾用 `value_struct_omit` 修复的模式，缺的是按本报告清单铺开。

---

## 2. 审计方法论（含证据链）

三层证据逐层收敛：

1. **静态比对**：`audit/extract_go.py` 解析全部 Go types.go（→ `go_types.json`，字段+json tag）；`audit/extract_rust.py`（v3 行状态机）解析全部 Rust pub struct（→ `rust_types.json`，字段+serde 属性）。提取器本轮修复 3 个 bug：`r#type` 字段正则、doc 注释中 `({})` 干扰花括号深度计数、struct 声明行自身 `{` 未入深度。修复后 1146→1149 struct（`policy/v1beta1::PodDisruptionBudgetSpec` 恢复完整 4 字段提取）。
2. **Go 反射 ground truth**：`audit/gozerogen/main.go` 在 k8s staging 源码上对每个注册类型 `json.Marshal(reflect.New(t).Interface())`，产出权威零值 JSON（`go_zero_full.json`，**1187 类型 / 65 个 GV**）。**消除对 Go omitempty 语义的推断错误**。⚠️ 本轮覆盖修正：apiextensions/v1+v1beta1（37 类型）与 apiregistration/v1+v1beta1（12 类型）不在 `k8s.io/api` 而在独立 staging 仓库（apiextensions-apiserver、kube-aggregator），初版注册表漏掉这 49 类型，本轮经 `registry2()`（[registry.go](audit/gozerogen/registry.go)）补齐——即本报告的 apiextensions/apiregistration 发现（§4.7/§4.8 CRD 条目、附录 A）全部来自该补全。
3. **Rust Default 序列化**：`serde_json::to_value(T::default())`（`rust_zero_full.json`，1131 类型；3 个无 Default derive 的类型单独核对：`NodeSwapStatus`/`DaemonEndpoint`/`ConfigMapNodeConfigSource`）。

原始 1284 条发现经人工复核剔除误报：VolumeSource/VolumeProjection/EnvVarSource 等 oneof-repr 类型（`VolumeSourceRepr` 枚举 + `VolumeSourceFieldsOwned` 承载全部字段，[sources.rs:62-105](taibai_api/src/core/v1/volume/sources.rs:62)）、Go `json:",inline"` 扁平化、`pub use` 再导出（admissionregistration/v1alpha1 8 个类型确认 re-export 自 v1，[v1alpha1/mod.rs:17-31](taibai_api/src/admissionregistration/v1alpha1/mod.rs:17)）。收敛为 **1142 条**（含后续实跑核实的 `CustomResourceSubresourceScale.specReplicasPath/statusReplicasPath` 4 行，见 §4.2）。

**覆盖完整性核验**（针对 "覆盖完了吗" 的回答，逐项可复现）：

| 维度 | 覆盖 | 核验方法 |
|---|---|---|
| Go 版本化 types.go 源文件 | **64 个全覆盖**（k8s.io/api 60 + apiextensions-apiserver 2 + kube-aggregator 2；两仓库另有 2 个 internal types.go 不在比对范围） | `find staging/src/k8s.io/api -name types.go \| wc -l` = 60；apiextensions/apiregistration 各 v1+v1beta1 |
| 静态提取 GV | 68 个（上述 64 + apimachinery 4：`meta/v1`、`runtime`、`intstr`、`resource-quantity`） | `go_types.json` 键集合 |
| 零值 ground truth GV | 65 个（68 − apimachinery 4；apimachinery 类型经 Rust `common/` 的命名映射单独核对：Timestamp/Quantity/IntOrString/ObjectMeta 等，见 §6 第 4 条） | `go_zero_full.json` 键集合 ∪ 静态集合 ⊇ 全部 64 版本化 GV |
| Rust 分组 | 67 个（64 个版本化 GV + `apiextensions` 根组 6 类型（JSONSchemaProps 系，Go 定义在 types_jsonschema.go，静态提取器只扫 types.go 故单独成组）+ `common`（apimachinery 映射）+ `testapigroup/v1`） | `rust_types.json` 键集合 |

补全经过：初版零值注册表只覆盖 `k8s.io/api`，漏掉独立 staging 仓库的 apiextensions（37 类型）与 apiregistration（12 类型）——静态比对**当时已覆盖**（desiredAPIVersion 名字错误即静态发现），但 P1-P9 零值比对从未在这 49 类型上运行。本轮 `registry2()` 补齐后新增 68 条字段级发现，加上实跑核实补录的 `CustomResourceSubresourceScale` 4 行，共 **72 条**（§4 各节标注 "本轮覆盖补全"）。`testapigroup` 是上游 K8s 测试夹具组（`src/testapigroup/mod.rs` 自述 "used in upstream Kubernetes tests"），非真实 API 组，不参与比对。

**为什么 849 个 wire_compat 用例全绿却拦不住这些问题**——两条证据：

- 证据 A：断言是对象级语义比较，非 JSON 键集合比较。[wire_compat/mod.rs:86-104](taibai_api/crates/taibai_api_testing/src/wire_compat/mod.rs:86)：
  ```rust
  let re_encoded: serde_json::Value = serde_json::to_value(&obj)...;
  assert_eq!(upstream, re_encoded, "...JSON semantic roundtrip mismatch");
  ```
  serde 对未知键静默忽略 → decode 一步丢数据后，对象级 roundtrip 无从发现。
- 证据 B：fixture 由 fuzz 生成，几乎不含零值。182 个 fixture 中仅 206 个空对象 + 2 个 null。抽查 `core.v1.Node.json` fixture 的 nodeInfo——全部字段非零（`"machineID": "machineIDValue"` 等），P4 类零值差异在该路径不可见。且 `core.v1.PodLogOptions` 被显式 skip（[wire_compat/core.rs:68](taibai_api/crates/taibai_api_testing/src/wire_compat/core.rs:68)："options type intentionally excluded"）。

---

## 3. 差异模式总览

| 模式 | 语义 | 字段 | 类型 | GV |
|---|---|---:|---:|---:|
| P1 | Go 值 struct 总输出 `{}`，Rust 缺席 | 452 | 311 | 61 |
| P8 | Go 无 omitempty slice 输出 `null`，Rust 缺席 | 161 | 150 | 49 |
| P4 | Go 无 omitempty string 输出 `""`，Rust 缺席 | 175 | 116 | 26 |
| P9 | Go 输出 `null`，Rust 输出 `[]` | 104 | 91 | 26 |
| P1b | 两侧都输出 struct 但内容不同 | 89 | 79 | 25 |
| P3 | Go `v1.Time`+omitempty 输出 `null`，Rust 缺席 | 62 | 48 | 26 |
| P4b | Go 无 omitempty int 输出 `0`，Rust 缺席 | 34 | 20 | 11 |
| P6 | Rust 泄漏非零默认值 | 28 | 26 | 21 |
| P5 | Rust 裸枚举默认值泄漏（Go 输出 `""`） | 29 | 29 | 16 |
| P2 | Go RawExtension 输出 `null`，Rust 缺席 | 6 | 2 | 2 |
| P7 | Go IntOrString 零值输出 `0`，Rust 缺席 | 2 | 2 | 2 |

零值形态对照实跑（同一类型两侧完整 JSON，`go_zero_full.json` vs `rust_zero_full.json`）：

```
core/v1::Pod        Go零值: {"metadata":{},"spec":{"containers":null},"status":{}}
                    Rust零值: {}
core/v1::Node       Go零值: {"metadata":{},"spec":{},"status":{"daemonEndpoints":{"kubeletEndpoint":{"Port":0}},
                            "nodeInfo":{"machineID":"","systemUUID":"",...共10个空串},"swap"...}}
                    Rust零值: {}
core/v1::Event      Go零值: {"metadata":{},"involvedObject":{},"source":{},"firstTimestamp":null,
                            "lastTimestamp":null,"eventTime":null,"reportingComponent":"","reportingInstance":""}
                    Rust零值: {"involvedObject":{}}
rbac/v1::ClusterRole  Go零值: {"metadata":{},"rules":null}
                      Rust零值: {"rules":[]}
admission/v1::AdmissionRequest  Go零值: {"uid":"","kind":{"group":"","version":"","kind":""},
                                "resource":{"group":"","version":"","resource":""},"operation":"",
                                "userInfo":{},"object":null,"oldObject":null,"options":null}
                                Rust零值: {"kind":{},"operation":"","resource":{},"uid":"","userInfo":{}}
apiextensions/v1::CustomResourceDefinitionSpec  Go零值: {"group":"","names":{"kind":"","plural":""},"scope":"","versions":null}
                                                Rust零值: {"names":{},"scope":"Namespaced"}
apiregistration/v1::APIService  Go零值: {"metadata":{},"spec":{"groupPriorityMinimum":0,"versionPriority":0},"status":{}}
                                Rust零值: {"spec":{"groupPriorityMinimum":0,"versionPriority":0},"status":{}}
```

---

## 4. 各模式详解（证据级）

### 4.1 P1 结构体值字段缺输出（452 字段 / 311 类型）

**机理**：Go `encoding/json` 对普通 struct 值类型**不应用 omitempty**（pre-Go1.24），永远输出 `{}`。taibai 建模为 `Option<T>` + `skip_serializing_if = "Option::is_none"` → 缺席。

**证据 1 — 顶层资源 metadata（163 个 GV-类型对）**：

Go（[types.go:5380-5385](kubernetes/staging/src/k8s.io/api/core/v1/types.go:5380)，Pod 的 `metadata` 是**值类型内嵌** + omitempty）：
```go
type Pod struct {
	metav1.TypeMeta `json:",inline"`
	metav1.ObjectMeta `json:"metadata,omitempty" protobuf:"bytes,1,opt,name=metadata"`
```
Rust（[pod.rs:42-44](taibai_api/src/core/v1/pod.rs:42)）：
```rust
#[serde(default, skip_serializing_if = "Option::is_none")]
pub metadata: Option<ObjectMeta>,
```
实跑零值：`Go零值: {"metadata":{},"spec":{"containers":null},"status":{}}` vs `Rust零值: {}`。

ConfigMap 同型（Go [types.go:7942](kubernetes/staging/src/k8s.io/api/core/v1/types.go:7942) `metav1.ObjectMeta \`json:"metadata,omitempty"\``；Rust [config.rs:31-32](taibai_api/src/core/v1/config.rs:31) `Option<ObjectMeta>`+skip；`Go零值: {"metadata":{}}` vs `Rust零值: {}`）。

本轮覆盖补全新增同型 4 例：`apiextensions/v1+v1beta1::CustomResourceDefinition(+List)`、`apiregistration/v1+v1beta1::APIService(+List)`——如 APIService：Go [kube-aggregator types.go:158](kubernetes/staging/src/k8s.io/kube-aggregator/pkg/apis/apiregistration/v1/types.go:158) `metav1.ObjectMeta \`json:"metadata,omitempty"\``；Rust [mod.rs:278-281](taibai_api/src/apiregistration/v1/mod.rs:278) `Option<ObjectMeta>`+skip（实跑对照见 §3 末行）。

**证据 2 — List metadata（112 个 GV-类型对）**：Go `PodList`/`ConfigMapList`/`EventList` 等的 `ListMeta` 值内嵌 + omitempty → `{}`。

**证据 3 — status/spec 值字段**：
- `ContainerStatus.state`（Go [types.go:3312](kubernetes/staging/src/k8s.io/api/core/v1/types.go:3312) `State ContainerState \`json:"state,omitempty"\`` 值类型；Rust [pod.rs:736-738](taibai_api/src/core/v1/pod.rs:736) `Option<ContainerState>`+skip）；
- `NodeStatus.daemonEndpoints`（Go [types.go:6505](kubernetes/staging/src/k8s.io/api/core/v1/types.go:6505) `DaemonEndpoints NodeDaemonEndpoints \`json:"daemonEndpoints,omitempty"\``；Rust [node.rs:170](taibai_api/src/core/v1/node.rs:170) `Option<NodeDaemonEndpoints>`+skip）→ Go 零值输出 `"daemonEndpoints":{"kubeletEndpoint":{"Port":0}}`，Rust 缺席；
- `NodeStatus.nodeInfo`（Go [types.go:6669](kubernetes/staging/src/k8s.io/api/core/v1/types.go:6669) 值类型；Rust [node.rs:174](taibai_api/src/core/v1/node.rs:174) `Option`+skip）。

**证据 4 — workload template**：`DeploymentSpec.template`（Go [types.go:205](kubernetes/staging/src/k8s.io/api/apps/v1/types.go:205) `Template v1.PodTemplateSpec \`json:"template"\`` **连 omitempty 都没有**；Rust [apps/v1/mod.rs:188-190](taibai_api/src/apps/v1/mod.rs:188) `Option<PodTemplateSpec>`+skip）。`JobSpec.template`、`CronJobSpec.jobTemplate`、`DaemonSetSpec.template` 同型。

**证据 5 — AdmissionRequest.kind**：Go `GroupVersionKind` 三个字段无 omitempty（[group_version.go:86-90](kubernetes/staging/src/k8s.io/apimachinery/pkg/apis/meta/v1/group_version.go:86)）：
```go
type GroupVersionKind struct {
	Group   string `json:"group" protobuf:"bytes,1,opt,name=group"`
	Version string `json:"version" ...`
	Kind    string `json:"kind" ...`
}
```
Rust [meta.rs:836-846](taibai_api/src/common/meta.rs:836) 三字段全 `String::is_empty` skip → Go 零值 `{"group":"","version":"","kind":""}` vs Rust `{}`（见 §3 实跑对照）。

**构成**（去重 229 个唯一 struct.field 对，版本扇出 452）：

| 字段角色 | 唯一对数 | 涉及 |
|---|---:|---|
| `metadata` | 140 | 163 顶层资源 + 112 List |
| `status` | 35 | 72 GV-类型对 |
| `spec` | 28 | 55 GV-类型对 |
| `template` | 5 | PodTemplateSpec ×12 |
| 其他值 struct | 21 | updateStrategy/loadBalancer/userInfo/state/lastState/kubeletEndpoint/nodeInfo/podSignature/limitResponse/parameters/source/deprecatedSource 等 |

**完整顶层类型清单**：见附录 A（本轮新增 apiextensions/v1+v1beta1 `CustomResourceDefinition(+List)`、apiregistration/v1+v1beta1 `APIService(+List)`）。

**影响**（TEP-0005 框架）：
- **热备切换**：同一 Pod 上游输出 `{"metadata":{},...}`、taibai 输出 `{}`——字节不等，切换即漂移（TEP-0005 §1 明确该场景要求 "完全相同的 JSON"）；
- **SSA/managedFields**：字段存在性是 patch 归属基本单位，键消失被记为字段删除（TEP-0005 明确 `{"resources":{}}` 与缺席是不同 patch 输入）；
- **GitOps**：任一形态差异触发持续 reconcile；
- **ControllerRevision.data**：DS/STS revision 逐字节比较，`template` 字段直接命中。

**修复方向**：`Option<T>` + `with = "crate::common::json_shape::value_struct_omit"`。该 policy 已存在（[json_shape.rs:6-40](taibai_api/src/common/json_shape.rs:6)）且已在 7 处使用（pod.rs:637、selector.rs:202、persistent_volume.rs:289、ephemeral.rs:81/210、internal/selector.rs:120、quantity/codec.rs:35）——是铺开问题，不是新造轮子。

### 4.2 P4 无 omitempty string 缺 `""`（175 字段 / 116 类型）

**机理**：Go `Name string \`json:"name"\`` → `"name":""`；taibai `String` + `skip_serializing_if = "String::is_empty"` → 缺席。**与已修复的 kubeProxyVersion 完全同类**。

**证据 1 — NodeSystemInfo 全部 10 个字段**（用户原始诉求的字段）：

Go（[types.go:6545-6565](kubernetes/staging/src/k8s.io/api/core/v1/types.go:6545)，10 个字段全部**无 omitempty**）：
```go
MachineID string `json:"machineID" protobuf:"bytes,1,opt,name=machineID"`
SystemUUID string `json:"systemUUID" ...`
BootID string `json:"bootID" ...`
KernelVersion string `json:"kernelVersion" ...`
OSImage string `json:"osImage" ...`
ContainerRuntimeVersion string `json:"containerRuntimeVersion" ...`
KubeletVersion string `json:"kubeletVersion" ...`
KubeProxyVersion string `json:"kubeProxyVersion" ...`   // ← 用户报告的 kubeProxyVersion 问题
OperatingSystem string `json:"operatingSystem" ...`
Architecture string `json:"architecture" ...`
```
Rust（[node.rs:390-398](taibai_api/src/core/v1/node.rs:390)，全部 `Option<String>` + skip；machineID/systemUUID/bootID 有 rename，其余连 rename 都不需要——问题在 omit）：
```rust
#[serde(default, skip_serializing_if = "Option::is_none")]
pub kubelet_version: Option<String>,
#[serde(default, skip_serializing_if = "Option::is_none")]
pub kube_proxy_version: Option<String>,
```
实跑零值：`Go零值: {"machineID":"","systemUUID":"","bootID":"","kernelVersion":"","osImage":"","containerRuntimeVersion":"","kubeletVersion":"","kubeProxyVersion":"","operatingSystem":"","architecture":""}` vs `Rust零值: {}`。
注：git 历史 commit 06e38ad 只修了 machineID/systemUUID/bootID 的 JSON **名字**，从未修 omit 行为。

**证据 2 — CronJobSpec.schedule**（无 omitempty）：Go [batch/v1/types.go:720](kubernetes/staging/src/k8s.io/api/batch/v1/types.go:720) `Schedule string \`json:"schedule"\``；Rust [batch/v1/mod.rs:617-619](taibai_api/src/batch/v1/mod.rs:617) `String` + `String::is_empty` skip。

**137 个唯一对**的完整分布（Top 类别）：
- 标识类：`EnvVar.name`、`Volume.name`、`VolumeMount.name`/`mountPath`、`VolumeDevice.name`/`devicePath`、`Taint.key`/`effect`、`ConfigMapKeySelector.key`、`SecretKeySelector.key`、`KeyToPath.key`/`path`、`ObjectFieldSelector.fieldPath`、`NodeSelectorRequirement.key`/`operator`、`TopologySpreadConstraint.topologyKey`/`whenUnsatisfiable`、`PodAffinityTerm.topologyKey` 等；
- 存储网络后端：`NFSVolumeSource.server`/`path`、`HostPathVolumeSource.path`、`GlusterfsVolumeSource.endpoints`/`path`、`ISCSIVolumeSource.targetPortal`/`iqn`、`CSIVolumeSource.driver`、`PersistentVolumeClaimVolumeSource.claimName`、`IngressServiceBackend.name`、`IPBlock.cidr`、`EndpointAddress.ip`、`PodIP.ip`、`HostIP.ip`；
- 设备（3 版本 ×3）：`AllocatedDeviceStatus.driver`/`pool`/`device`；
- 发现（2 版本）：`APIResourceDiscovery.resource`/`singularResource`、`APISubresourceDiscovery.subresource`、`APIVersionDiscovery.version`、`MetricIdentifier.name`；
- webhook/CEL：`MutatingWebhook.name`、`ValidatingWebhook.name`、`Validation.expression`、`MatchCondition.name`/`expression`、`Variable.name`/`expression`、`AuditAnnotation.key`/`valueExpression`、`ExpressionWarning.fieldRef`/`warning`；
- 其他：`ContainerStatus.image`/`imageID`、`EphemeralContainer(Common).name`、`Event.reportingComponent`/`reportingInstance`（core）、`LimitRangeItem.type`、`SeccompProfile.type`、`AppArmorProfile.type`、`TypedLocalObjectReference.kind`/`name`、`Sysctl.name`/`value`、`HTTPHeader.name`/`value`、`ContainerResizePolicy.resourceName`/`restartPolicy`、`LeaseCandidateSpec.leaseName`/`binaryVersion`、`PriorityLevelConfigurationSpec.type`（4 版本）、`CertificateSigningRequestSpec.signerName`、`ModifyVolumeStatus.status`、`ReplicationControllerCondition.type`/`status`、`PodFailurePolicyOnPodConditionsPattern.type`/`status`、`DeploymentRollback.name`、autoscaling 各 `metricName`/`container`、`RangeAllocation.range`、`ClusterTrustBundleSpec.trustBundle`、`TokenRequestStatus.token`、`FileKeySelector.{volumeName,key,path}`、`AttachedVolume.{name,devicePath}`、`DownwardAPIVolumeFile.path`、`NodeAddress.address`、`NodeRuntimeHandler.name`、`ResourceClaim.name`、`PodResourceClaim(.Status).name`、`ScopedResourceSelectorRequirement.{scopeName,operator}`、`LocalVolumeSource.path`、`ServiceAccountTokenProjection.path`、`ClusterTrustBundleProjection.path`、`TypedObjectReference.{kind,name}`、`VolumeMountStatus.{name,mountPath}`；
- **apiextensions/apiregistration（本轮覆盖补全新增 30 对）**：`CustomResourceColumnDefinition.{type,name,jsonPath}`（v1beta1 wire 名是 `JSONPath`，`rename` 已正确——[v1beta1/mod.rs:372](taibai_api/src/apiextensions/v1beta1/mod.rs:372)；Go [v1beta1/types.go:288](kubernetes/staging/src/k8s.io/apiextensions-apiserver/pkg/apis/apiextensions/v1beta1/types.go:288) tag 即 `JSONPath`，v1 是 camelCase `jsonPath`，两侧命名均核对无错）、`SelectableField.jsonPath`、`CustomResourceDefinitionNames.{plural,kind}`、`CustomResourceDefinitionSpec.group`、`CustomResourceDefinitionVersion.name`、`ConversionRequest.{uid,desiredAPIVersion}`（名字错误见 §5）、`ConversionResponse.uid`、`ServiceReference.{namespace,name}`、**`CustomResourceSubresourceScale.{specReplicasPath,statusReplicasPath}`（实跑验证：Go 零值 `{"specReplicasPath":"","statusReplicasPath":""}`，[types.go:453](kubernetes/staging/src/k8s.io/apiextensions-apiserver/pkg/apis/apiextensions/v1/types.go:453) 与 [types.go:459](kubernetes/staging/src/k8s.io/apiextensions-apiserver/pkg/apis/apiextensions/v1/types.go:459) 两字段均无 omitempty；Rust [mod.rs:552-559](taibai_api/src/apiextensions/v1/mod.rs:552) `String`+`String::is_empty` skip → `{}`。初版 Rust 零值注册表漏掉该类型导致比对缺席，本轮补录 4 行）**。

**影响**：`NodeSystemInfo` 是 kubelet 上报的状态子对象，`kubectl get node -o json` 直接可见漂移；标识类字段（name/key）在真实负载几乎非零，影响集中于零值路径（fuzz、模板生成、PATCH 部分字段对象）。

**修复方向**：`String` 去 skip（值字段）或 `Option<String>` + 输出 `""` 的 scalar policy（`value_scalar_omit::is_none_or_zero_i32/i64` 已在 [json_shape.rs:131-135](taibai_api/src/common/json_shape.rs:131)，字符串版需补）。

### 4.3 P8 无 omitempty slice 缺 `null`（161 字段 / 150 类型）

**机理**：Go nil slice 无 omitempty → `null`；taibai `Vec<T>` + `skip_serializing_if = "Vec::is_empty"` → 缺席。

**证据 1 — PodList.items / EventList.items 等 78 处**：
Go（[types.go:5414](kubernetes/staging/src/k8s.io/api/core/v1/types.go:5414)）：
```go
Items []Pod `json:"items" protobuf:"bytes,2,rep,name=items"`   // 无 omitempty
```
Rust（[event.rs:148-153](taibai_api/src/core/v1/event.rs:148)，EventList）：
```rust
#[serde(default, skip_serializing_if = "Vec::is_empty",
    deserialize_with = "crate::common::deserialize_null_default")]
pub items: Vec<Event>,
```
注意 decode 侧已有 `deserialize_null_default`（null→空），**encode 侧是缺口**。

**证据 2 — DeploymentSpec.selector**（Go [apps/v1/types.go:386](kubernetes/staging/src/k8s.io/api/apps/v1/types.go:386) `Selector *metav1.LabelSelector \`json:"selector"\``——指针且**无 omitempty** → `null`；Rust [apps/v1/mod.rs:184-186](taibai_api/src/apps/v1/mod.rs:184) `Option<LabelSelector>`+skip → 缺席）。

**证据 3 — MutatingWebhook.admissionReviewVersions**（Go [types.go:911](kubernetes/staging/src/k8s.io/api/admissionregistration/v1/types.go:911) `AdmissionReviewVersions []string \`json:"admissionReviewVersions"\`` 无 omitempty；Rust [mod.rs:784-787](taibai_api/src/admissionregistration/v1/mod.rs:784) `Vec<String>`+skip）。

**证据 4 — DRA DeviceClaim.requests**（Go [resource/v1/types.go:725](kubernetes/staging/src/k8s.io/api/resource/v1/types.go:725) `Requests []DeviceRequest \`json:"requests"\``；Rust [resource_claim.rs:64-68](taibai_api/src/resource/v1/resource_claim.rs:64) `Vec`+skip；v1beta1/v1beta2 同）。

**证据 5 — CRD Spec.versions（本轮覆盖补全）**：Go [apiextensions/v1/types.go:60](kubernetes/staging/src/k8s.io/apiextensions-apiserver/pkg/apis/apiextensions/v1/types.go:60) `Versions []CustomResourceDefinitionVersion \`json:"versions"\``（无 omitempty → `null`）；Rust [mod.rs:157](taibai_api/src/apiextensions/v1/mod.rs:157) `Vec`+`Vec::is_empty` skip（decode 侧同样已有 `deserialize_null_default`）→ 缺席。

**98 个唯一对**分布：List.items ×78（本轮新增 `CustomResourceDefinitionList.items` v1+v1beta1、`APIServiceList.items` v1+v1beta1）；workload selector ×4（apps v1+v1beta2 的 DS/Deploy/RS/STS）；webhook 数组 ×4（`admissionReviewVersions`/`sideEffects` ×2）；DRA ×12（`DeviceClaim.requests`、`AllocatedDeviceStatus.conditions`、`ResourceSliceSpec.devices`、`CapacityRequestPolicy.default` 各 3 版本）；发现/RBAC ×8（`APIResourceDiscovery.verbs`、`APISubresourceDiscovery.verbs`、`NonResourceRule.verbs`、`ResourceRule.verbs`、`SubjectRulesReviewStatus.resourceRules`/`nonResourceRules`）；HPA ×5（`currentMetrics`、`conditions` 等）；**apiextensions CRD 核心 ×7（v1+v1beta1）：`CustomResourceDefinitionSpec.versions`、`CustomResourceDefinitionStatus.conditions`/`storedVersions`、`ConversionRequest.objects`、`ConversionResponse.convertedObjects`、`WebhookConversion.conversionReviewVersions`**——CRD 版本清单与转换 webhook 载荷的数组字段全部缺席；其余：`EndpointSlice.endpoints`/`ports`、`HTTPIngressRuleValue.paths`（Go [networking/v1/types.go:443](kubernetes/staging/src/k8s.io/api/networking/v1/types.go:443) `Paths []HTTPIngressPath \`json:"paths"\``；Rust [ingress.rs:226-230](taibai_api/src/networking/v1/ingress.rs:226) `Vec`+skip）、`TokenRequestSpec.audiences` 等。

**影响**：**任何空 List 的 GET 响应**（`kubectl get pods` 空命名空间 → `items:null`）shape 不等。SMP 中 null 与缺席是不同 patch 输入。

**修复方向**：去 skip（`Vec` 序列化空时输出 `[]` 是错的——应为 `null`），需 `Option<Vec<T>>` 或 `serialize_null` policy：Go 无 omitempty → nil 输出 null。

### 4.4 P9 Go `null` vs Rust `[]`（104 字段 / 91 类型）

**机理**：同 P8 的 Go 侧（无 omitempty slice → null），但 taibai 侧输出了空数组（serde(default) 无 skip 或转换层补 `[]`）。

**证据 — ClusterRole.rules**（3 版本）：
Go（[rbac/v1/types.go:191](kubernetes/staging/src/k8s.io/api/rbac/v1/types.go:191)）：
```go
Rules []PolicyRule `json:"rules" protobuf:"bytes,2,rep,name=rules"`   // 无 omitempty
```
Rust（[rbac/v1/mod.rs](taibai_api/src/rbac/v1/mod.rs) `rules` 建模输出 `[]`）——实跑零值：`Go零值: {"metadata":{},"rules":null}` vs `Rust零值: {"rules":[]}`。

**44 个唯一对**分布：List.items ×57（FlowSchemaList、PriorityLevelConfigurationList、DeploymentList、ControllerRevisionList、CSIStorageCapacityList、VolumeAttachmentList 等）；flowcontrol 最集中（`NonResourcePolicyRule.verbs`/`nonResourceURLs`、`ResourcePolicyRule.verbs`/`apiGroups`/`resources`/`namespaces`、`PolicyRulesWithSubjects.subjects` 各 4 版本）；rbac（`ClusterRole.rules`、`Role.rules`、`PolicyRule.verbs` 各 3 版本）；storage；其他：`CertificateSigningRequestSpec.request`、`Endpoint.addresses`、`PodFailurePolicy.rules`、`SuccessPolicy.rules`、`RBDPersistentVolumeSource.monitors` 等。

**影响**：与 P8 镜像。**关键：SMP 中 `null` 是删除列表语义**（null override），`[]` 只是空列表——这是 patch 语义实质差异，非仅字节差异。

### 4.5 P1b 两侧都输出 struct 但内容不同（89 字段 / 79 类型）

**构成 1 — List metadata `null` vs `{}`（21 处）**：
Go（[core/v1/types.go:8044](kubernetes/staging/src/k8s.io/api/core/v1/types.go:8044) ComponentStatusList）：
```go
metav1.ListMeta `json:"metadata,omitempty" ...`   // 值类型 → {}
```
Rust（[component_status.rs:55-57](taibai_api/src/core/v1/component_status.rs:55)）：
```rust
#[serde(default)]                    // ← 无 skip_serializing_if
pub metadata: Option<ListMeta>,      // None → 序列化为 null
```
同型 21 处：networking v1/v1beta1 各 List（IPAddressList、IngressClassList、IngressList、NetworkPolicyList、ServiceCIDRList）、resource 三个版本各 List（DeviceClassList、ResourceClaimList、ResourceClaimTemplateList、ResourceSliceList）+ v1alpha3 DeviceTaintRuleList + core ComponentStatusList。实跑：`go={}` vs `rust=null`（`findings_table.json` 21 行）。

**构成 2 — autoscaling 指标嵌套（10 处）**：`ContainerResourceMetricSource.target`、`ResourceMetricSource.target`——Go 零值 `{"type":""}` vs Rust `{"type":"Utilization"}`（P5 复合，见 4.7）。

**构成 3 — DRA spec 链（15 处）**：`ResourceClaimSpec.devices`——Go（[resource/v1/types.go:710](kubernetes/staging/src/k8s.io/api/resource/v1/types.go:710)）`Devices DeviceClaim \`json:"devices"\`` 值类型，内嵌 `Requests []DeviceRequest \`json:"requests"\``（[types.go:725](kubernetes/staging/src/k8s.io/api/resource/v1/types.go:725) 无 omitempty）→ `{"devices":{"requests":null}}`；Rust（[resource_claim.rs:54-56](taibai_api/src/resource/v1/resource_claim.rs:54)）`devices: DeviceClaim`（serde default，总输出），但内部 requests skip → `{"devices":{}}`。实跑零值链：`ResourceClaim.spec go={"devices": {"requests": null}}` vs `rust={"devices": {}}`。

**构成 4 — 其他**：`AdmissionRequest.kind`/`resource`（GVK 内三字段全 skip，见 4.1 证据 5）、`ValidatingAdmissionPolicy.status`、`MutatingAdmissionPolicy.spec`、`CronJobSpec.jobTemplate`、`CertificateSigningRequest.spec`、`CSINode.spec`、`JobSpec.template`、`DaemonSetSpec.template`、`DeploymentSpec.template`、`HTTPIngressPath.backend`、`TokenRequest.spec`、`ClusterTrustBundle.spec`、`PodCertificateRequest.spec`、`EventSource`、`UserInfo`（admission）等。

**构成 5 — apiextensions CRD 链（本轮覆盖补全新增 10 行）**：`CustomResourceDefinitionSpec`——Go 零值 `{"group":"","names":{"kind":"","plural":""},"scope":"","versions":null}` vs Rust `{"names":{},"scope":"Namespaced"}`（`group` 缺 P4、`versions` 缺 P8、`scope` 枚举泄漏 P5 的**复合叠加**，见 §3 实跑对照）；`CustomResourceDefinitionNames`——Go `{"kind":"","plural":""}` vs Rust `{}`；`CustomResourceDefinitionStatus`——Go `{"acceptedNames":{"kind":"","plural":""},"conditions":null,"storedVersions":null}` vs Rust `{"acceptedNames":{}}`；`ConversionResponse.result`——Go `{"metadata":{}}` vs Rust `{}`（Go [types.go:517](kubernetes/staging/src/k8s.io/apiextensions-apiserver/pkg/apis/apiextensions/v1/types.go:517) `Result metav1.Status \`json:"result" ...\`` 值类型总输出）。

**影响**：嵌套 shape 差异随深度放大；ControllerRevision 逐字节比较直接命中 `template`/`jobTemplate` 类字段。

### 4.6 P3 `v1.Time`+omitempty → `null` vs 缺席（62 字段 / 48 类型）

**机理证据**——Go `metav1.Time` 自定义 MarshalJSON（[time.go:162-165](kubernetes/staging/src/k8s.io/apimachinery/pkg/apis/meta/v1/time.go:162)）：
```go
func (t Time) MarshalJSON() ([]byte, error) {
	if t.IsZero() {
		// Encode unset/nil objects as JSON's "null".
		return []byte("null"), nil
	}
```
**值类型 + 自定义 MarshalJSON → omitempty 无效，零值输出 `null`**。taibai `Option<Timestamp>` + skip → 缺席。

**证据 — DeploymentCondition.lastUpdateTime / lastTransitionTime**：
Go（[apps/v1/types.go:557-559](kubernetes/staging/src/k8s.io/api/apps/v1/types.go:557)）：
```go
LastUpdateTime metav1.Time `json:"lastUpdateTime,omitempty" ...`
LastTransitionTime metav1.Time `json:"lastTransitionTime,omitempty" ...`
```
Rust（[apps/v1/mod.rs:700-707](taibai_api/src/apps/v1/mod.rs:700)）：`last_update_time: Option<String>` + skip（注意还是 `Option<String>` 不是 `Option<Timestamp>`）。

**证据 — 对照组（正确实现）**：`ObjectMeta.creationTimestamp` 在 taibai 已用 `value_struct_omit_zero` + `is_none_or_zero_timestamp`（[meta.rs:341-355](taibai_api/src/common/meta.rs:341)），对应 Go [types.go:188](kubernetes/staging/src/k8s.io/apimachinery/pkg/apis/meta/v1/types.go:188) `CreationTimestamp Time \`json:"creationTimestamp,omitempty,omitzero"\``——**该字段不在差异清单里，证明 policy 有效**，其余 62 处未铺开。

**35 个唯一对**：`DeploymentCondition.{lastUpdateTime,lastTransitionTime}`（4 版本）、`HorizontalPodAutoscalerCondition.lastTransitionTime`（4）、`FlowSchemaCondition.lastTransitionTime`（4）、`PriorityLevelConfigurationCondition.lastTransitionTime`（4）、`DaemonSetCondition`/`ReplicaSetCondition`/`StatefulSetCondition`/`JobCondition`/`NamespaceCondition`/`NodeCondition`/`PodCondition`/`PersistentVolumeClaimCondition`/`ReplicationControllerCondition`/`CertificateSigningRequestCondition`/`StorageVersionCondition`/`MigrationCondition` 的 `lastTransitionTime`（JobCondition/PVC 另有 `lastProbeTime`）、`ContainerStateRunning.startedAt`、`ContainerStateTerminated.startedAt`/`finishedAt`、`Event.{firstTimestamp,lastTimestamp,eventTime,deprecatedFirstTimestamp,deprecatedLastTimestamp}`、`EventSeries.lastObservedTime`、`VolumeError.time`，以及本轮覆盖补全的 `CustomResourceDefinitionCondition.lastTransitionTime`（apiextensions v1+v1beta1，Go [types.go:346](kubernetes/staging/src/k8s.io/apiextensions-apiserver/pkg/apis/apiextensions/v1/types.go:346) `LastTransitionTime metav1.Time \`json:"lastTransitionTime,omitempty"\``）与 `APIServiceCondition.lastTransitionTime`（apiregistration v1+v1beta1，Go [kube-aggregator types.go:126](kubernetes/staging/src/k8s.io/kube-aggregator/pkg/apis/apiregistration/v1/types.go:126)；Rust [mod.rs:235](taibai_api/src/apiregistration/v1/mod.rs:235) `Option<Timestamp>`+skip）。

**影响**：条件对象是 controller 高频读写路径；Event 时间戳 null 在 `kubectl describe` 语义里表示未发生。修复用已有 `value_struct_omit_zero`（Timestamp 已有 is_zero）。

### 4.7 P5 裸枚举默认值泄漏（29 字段 / 29 类型）

**机理**：Go 枚举是字符串类型别名（`type FlowDistinguisherMethodType string`），零值输出 `""`；taibai 裸 enum + `#[default]` → 零值输出该变体。**Rust 编造了 Go 没有的数据**。

**证据 1 — FlowDistinguisherMethod.type**：
Go（[flowcontrol/v1/types.go:186-190](kubernetes/staging/src/k8s.io/api/flowcontrol/v1/types.go:186)）：
```go
type FlowDistinguisherMethod struct {
	// `type` is the type of flow distinguisher method
	// The supported types are "ByUser" and "ByNamespace".
	// Required.
	Type FlowDistinguisherMethodType `json:"type" protobuf:"bytes,1,opt,name=type"`
}
```
（`FlowDistinguisherMethodType` 是 `type ... string` 别名，零值 `""`。）
Rust（[flowcontrol/v1/mod.rs:170-188](taibai_api/src/flowcontrol/v1/mod.rs:170)）：
```rust
pub struct FlowDistinguisherMethod {
    #[serde(rename = "type")]
    pub r#type: FlowDistinguisherMethodType,   // 裸 enum
}
pub enum FlowDistinguisherMethodType {
    #[serde(rename = "ByUser")]
    #[default]          // ← 零值泄漏 "ByUser"
    ByUser,
```

**证据 2 — MetricTarget.type**：Go [autoscaling/v2/types.go:364-366](kubernetes/staging/src/k8s.io/api/autoscaling/v2/types.go:364) `Type MetricTargetType \`json:"type"\``（类型别名，零值 `""`）；Rust [autoscaling/v2/mod.rs:442-467](taibai_api/src/autoscaling/v2/mod.rs:442) 裸 enum `MetricTargetType` + `#[default] Utilization` → 输出 `"Utilization"`。

**证据 3 — EndpointSlice.addressType**：Go [discovery/v1/types.go:51](kubernetes/staging/src/k8s.io/api/discovery/v1/types.go:51) `AddressType AddressType \`json:"addressType"\``；Rust [discovery/v1/mod.rs:57-59](taibai_api/src/discovery/v1/mod.rs:57) 裸 enum + `#[default] IPv4`（[mod.rs:21-25](taibai_api/src/discovery/v1/mod.rs:21)）。

**证据 4 — CRD scope/strategy（本轮覆盖补全，apiextensions v1+v1beta1，最严重的 P5 案例）**：

Go（[apiextensions/v1/types.go:282](kubernetes/staging/src/k8s.io/apiextensions-apiserver/pkg/apis/apiextensions/v1/types.go:282)）：
```go
// ResourceScope is an enum defining the different scopes available to a custom resource
type ResourceScope string          // ← 纯字符串别名，零值 ""
const (
	ClusterScoped   ResourceScope = "Cluster"
	NamespaceScoped ResourceScope = "Namespaced"
)
```
`Spec.Scope ResourceScope \`json:"scope"\``（[types.go:50](kubernetes/staging/src/k8s.io/apiextensions-apiserver/pkg/apis/apiextensions/v1/types.go:50)）——无 omitempty → 零值输出 `"scope":""`。

Rust（[apiextensions/v1/mod.rs:37-47](taibai_api/src/apiextensions/v1/mod.rs:37)）：
```rust
#[derive(..., Default)]
#[serde(rename_all = "PascalCase")]
pub enum ResourceScope {
    Cluster,
    #[default]          // ← 零值泄漏 "Namespaced"
    Namespaced,
}
```
`pub scope: ResourceScope`（[mod.rs:148](taibai_api/src/apiextensions/v1/mod.rs:148)，`#[serde(default)]` 值字段总输出）→ Rust 零值输出 `"scope":"Namespaced"`。实跑对照（§3）：`CustomResourceDefinitionSpec` Go `{"scope":""}` vs Rust `{"scope":"Namespaced"}`。

同型：`CustomResourceConversion.strategy`——Go [types.go:26](kubernetes/staging/src/k8s.io/apiextensions-apiserver/pkg/apis/apiextensions/v1/types.go:26) `type ConversionStrategyType string`，[types.go:81](kubernetes/staging/src/k8s.io/apiextensions-apiserver/pkg/apis/apiextensions/v1/types.go:81) `Strategy ConversionStrategyType \`json:"strategy"\`` 零值 `""`；Rust [mod.rs:24-30](taibai_api/src/apiextensions/v1/mod.rs:24) 裸 enum `#[default] None` + [mod.rs:178](taibai_api/src/apiextensions/v1/mod.rs:178) `pub strategy: ConversionStrategyType` → 输出 `"None"`。Go 的 `"None"` 是**合法枚举值**（NoneConverter），Rust 把 "零值" 冒充 "显式选择 None 策略"——语义不可逆：下游无法区分 CRD 是真配了 None 转换还是根本没配。

**全部 29 处**：`Mutation.patchType`→"ApplyConfiguration"（v1alpha1+v1beta1）、`APIResourceDiscovery.scope`→"Cluster"（apidiscovery v2+v2beta1）、`HPAScalingPolicy.type`→"Pods"（autoscaling v2+v2beta2）、`MetricTarget.type`→"Utilization"（同）、`PodFailurePolicyOnExitCodesRequirement.operator`→"In"（batch/v1）、`PodFailurePolicyRule.action`→"FailJob"（batch/v1）、`EndpointSlice.addressType`→"IPv4"（discovery v1+v1beta1）、`IngressPortStatus.protocol`→"TCP"（extensions/v1beta1）、`FlowDistinguisherMethod.type`→"ByUser"（flowcontrol v1+v1beta1+v1beta2+v1beta3）、`LimitResponse.type`→"Queue"（同 4 版本）、`Subject.kind`→"User"（同 4 版本）、**`CustomResourceDefinitionSpec.scope`→"Namespaced"（apiextensions v1+v1beta1）**、**`CustomResourceConversion.strategy`→"None"（apiextensions v1+v1beta1）**。

**影响**：**比缺字段危险**——HPA controller 把编造的 "Utilization" 当真实配置消费；flowcontrol 把空 Subject 解析成 User 类；CRD 的 `scope:"Namespaced"`/`strategy:"None"` 直接改变 CRD 语义（Cluster 范围 CRD 与 Namespaced 是两类资源，None 转换与未配置是两种状态）。虚假默认语义不可逆（下游无法区分 "显式设置" 与 "Rust 编造"）。

**修复方向**：裸 enum → `String` 或无默认 enum + `""` 映射。`PriorityLevelConfigurationSpec.type` 亦此类（Rust [mod.rs:445-450](taibai_api/src/flowcontrol/v1/mod.rs:445) `Option<PriorityLevelEnablement>`+skip vs Go [types.go:432](kubernetes/staging/src/k8s.io/api/flowcontrol/v1/types.go:432) `Type PriorityLevelEnablement \`json:"type"\`` 输出 `""`）。

### 4.8 P6 Rust 默认值泄漏（28 字段 / 26 类型）

**机理**：k8s **apiserver 默认值**（defaulting 阶段）被烧进 serde Default，或 bool/String 无 skip。

**证据 — RollingUpdateDeployment.maxSurge/maxUnavailable（状态污染典型）**：
Go（[apps/v1/types.go:455-467](kubernetes/staging/src/k8s.io/api/apps/v1/types.go:455)）：
```go
type RollingUpdateDeployment struct {
	// ...
	// Defaults to 25%.            ← 注释说明这是 apiserver defaulting，
	// +optional                     不发生在序列化层
	MaxUnavailable *intstr.IntOrString `json:"maxUnavailable,omitempty" ...`
```
Rust（[apps/v1/mod.rs:459-467](taibai_api/src/apps/v1/mod.rs:459)）：
```rust
impl Default for RollingUpdateDeployment {
    fn default() -> Self {
        Self {
            max_unavailable: Some(IntOrString::String("25%".to_string())),  // ← 泄漏
            max_surge: Some(IntOrString::String("25%".to_string())),
        }
    }
}
```
实跑零值：`rust_wire="25%"`（`findings_table.json` 对应行），Go 侧 omitempty 指针 → 缺席。

**证据 — CronJobSpec.concurrencyPolicy**：Go [batch/v1/types.go:746](kubernetes/staging/src/k8s.io/api/batch/v1/types.go:746) `ConcurrencyPolicy ConcurrencyPolicy \`json:"concurrencyPolicy,omitempty"\``（omitempty 对字符串别名有效，空值缺席）；Rust [batch/v1/mod.rs:628-635](taibai_api/src/batch/v1/mod.rs:628) `concurrency_policy: ConcurrencyPolicy` 裸 enum + `#[default] Allow`（[mod.rs:686-689](taibai_api/src/batch/v1/mod.rs:686)）→ 输出 `"Allow"`。

**证据 — CRD 列定义 priority（本轮覆盖补全）**：Go [apiextensions/v1/types.go:245](kubernetes/staging/src/k8s.io/apiextensions-apiserver/pkg/apis/apiextensions/v1/types.go:245) `Priority int32 \`json:"priority,omitempty"\``（omitempty 对 int 有效 → 零值缺席）；Rust [apiextensions/v1/mod.rs:343-346](taibai_api/src/apiextensions/v1/mod.rs:343) `#[serde(default)] pub priority: i32` 值字段无 skip → 输出 `"priority":0`。v1beta1 同型（[mod.rs:369](taibai_api/src/apiextensions/v1beta1/mod.rs:369)，Go [v1beta1/types.go:285](kubernetes/staging/src/k8s.io/apiextensions-apiserver/pkg/apis/apiextensions/v1beta1/types.go:285)）。

**全部 28 处**：`RollingUpdateDeployment.maxSurge/maxUnavailable`→"25%"（apps v1+v1beta1）、`RollingUpdateDaemonSet.maxUnavailable`→1、`RollingUpdateStatefulSetStrategy.partition`→0（2 版本）、`CronJobSpec.concurrencyPolicy`→"Allow"（batch v1+v1beta1）、`PriorityClass.globalDefault`→false（scheduling v1+v1alpha1+v1beta1）、`ValidatingAdmissionPolicyStatus.observedGeneration`→0（admissionregistration v1+v1alpha1）、`SubjectAccessReviewStatus.denied`→false（authorization v1+v1beta1）、`TokenReviewStatus.authenticated`→false、`MutatingAdmissionPolicySpec.reinvocationPolicy`→"Never"（v1alpha1+v1beta1）、`extensions/v1beta1 DeploymentSpec.paused`→false、`events/v1 Event.deprecatedCount`→0、`DeviceConstraint.matchAttribute`→""（resource/v1）、`ResourceClaimConsumerReference.apiGroup`→""（3 版本）、`PodDNSConfigOption.name`→""、**`CustomResourceColumnDefinition.priority`→0（apiextensions v1+v1beta1）**。

**影响**：`maxUnavailable:"25%"` 泄漏后，上游 etcd 中未设置该字段的 Deployment 被 taibai 读出写回即**永久写入 25%**——状态污染，非 shape 差异。ControllerRevision 逐字节比较直接误判 revision 变化。`globalDefault=false`/`denied=false` 类是 bool 无 skip 的 P4 同型。

**修复方向**：把 apiserver 默认值从 serde Default 挪到 defaulting 函数（k8s 语义上 defaulting 是独立阶段）；bool/String 加 skip 或 Option。

### 4.9 P2 RawExtension `null` vs 缺席（6 字段）+ P7 IntOrString（2 字段）

**P2 证据**：Go `runtime.RawExtension` 自定义 MarshalJSON（[extension.go:98-108](kubernetes/staging/src/k8s.io/apimachinery/pkg/runtime/extension.go:98)）：
```go
func (re RawExtension) MarshalJSON() ([]byte, error) {
	if re.Raw == nil {
		...
		return []byte("null"), nil   // ← 零值输出 null
	}
```
Go [admission/v1/types.go:99-102](kubernetes/staging/src/k8s.io/api/admission/v1/types.go:99)：`Object runtime.RawExtension \`json:"object,omitempty"\``——omitempty 对自定义 MarshalJSON 的值类型无效 → `"object":null`。
Rust（[admission/v1/mod.rs:114](taibai_api/src/admission/v1/mod.rs:114)）：`pub object: Option<Value>` + skip → 缺席。
实跑零值对照（§3）：Go `"object":null,"oldObject":null,"options":null` vs Rust 三键全缺席。

**P7 证据**：Go [core/v1/types.go:6137](kubernetes/staging/src/k8s.io/api/core/v1/types.go:6137) `TargetPort intstr.IntOrString \`json:"targetPort,omitempty"\``（[intstr.go:41-45](kubernetes/staging/src/k8s.io/apimachinery/pkg/util/intstr/intstr.go:41) 值类型，零值 Type=Int/IntVal=0 → `0`）；Rust [service.rs:240-242](taibai_api/src/core/v1/service.rs:240) `Option<IntOrString>`+skip → 缺席。`extensions/v1beta1::IngressBackend.servicePort` 同型。

**P2 影响**：admission webhook 生态——`req.Object == null` 是 webhook 框架判断 DELETE 的通用模式（缺席在宽松 decode 下等价，shape 层不等）。修复极简：去 skip（serde `Option` None 默认序列化 null）。

### 4.10 结构性缺失字段（34 个）— S0

**类型里根本没有该字段**：反序列化静默丢数据，序列化无法表达。

**resource/DRA（25 个，1.34 新特性字段）**：

`DeviceRequestAllocationResult`（Go [resource/v1/types.go:1476-1580](kubernetes/staging/src/k8s.io/api/resource/v1/types.go:1476)，字段清单含 tag 5-10）：
```go
AdminAccess *bool `json:"adminAccess,omitempty" protobuf:"bytes,5,opt,name=adminAccess"`
Tolerations []DeviceToleration `json:"tolerations,omitempty" ...`
BindingConditions []string `json:"bindingConditions,omitempty" protobuf:"bytes,7,..."`
BindingFailureConditions []string `json:"bindingFailureConditions,omitempty" protobuf:"bytes,8,..."`
ShareID *types.UID `json:"shareID,omitempty" protobuf:"bytes,9,opt,name=shareID"`
ConsumedCapacity map[QualifiedName]resource.Quantity `json:"consumedCapacity,omitempty" protobuf:"bytes,10,..."`
```
Rust v1（[resource_claim.rs:406-421](taibai_api/src/resource/v1/resource_claim.rs:406)）只有 request/driver/pool/device/tolerations——**缺 5 个**。
Rust v1beta2（[resource_claim.rs:371](taibai_api/src/resource/v1beta2/resource_claim.rs:371)）只有 request/driver/pool/device/tolerations——**缺 5 个，且比 v1beta1（[resource_claim.rs:364-405](taibai_api/src/resource/v1beta1/resource_claim.rs:364)，有 adminAccess/bindingConditions/bindingFailureConditions/share_id）还少 3 个，版本回退**。
Rust v1beta1 缺 ShareID（名字还错，§5）与 ConsumedCapacity。
`AllocatedDeviceStatus.shareID`（Go [types.go:1818](kubernetes/staging/src/k8s.io/api/resource/v1/types.go:1818) `ShareID *string \`json:"shareID,omitempty"\``）：v1/v1beta1/v1beta2 三版本 Rust 均缺失（v1beta1/v1beta2 有 share_id 字段但 JSON 名错）。
`DeviceConstraint.distinctAttribute`（Go [types.go:1230](kubernetes/staging/src/k8s.io/api/resource/v1/types.go:1230)）：Rust v1 [resource_claim.rs:261-272](taibai_api/src/resource/v1/resource_claim.rs:261) 只有 requests/match_attribute。
注：internal 版本（[internal/resource_claim.rs:292-313](taibai_api/src/resource/internal/resource_claim.rs:292)）字段齐全（adminAccess/bindingConditions/bindingFailureConditions/share_id/consumed_capacity），说明**内部类型有、版本化类型漏同步**；但 internal 的 `consumed_capacity: BTreeMap<String,String>` 与 Go `map[QualifiedName]resource.Quantity` 类型不符。

**core/v1（14 个）**：

- `EphemeralContainerCommon`（Rust [ephemeral.rs:158-241](taibai_api/src/core/v1/ephemeral.rs:158)，止于 security_context，共 21 字段）缺 Go（[types.go:5005-5162](kubernetes/staging/src/k8s.io/api/core/v1/types.go:5005)）的 8 个字段：`ResizePolicy`（[5073](kubernetes/staging/src/k8s.io/api/core/v1/types.go:5073)）、`RestartPolicy`（5079）、`RestartPolicyRules`（5086）、`TerminationMessagePath`（5137）、`TerminationMessagePolicy`（5147）、`Stdin`（5157）、`StdinOnce`（5160）、`TTY`（5162）。这些字段在 `EphemeralContainer` wrapper（[ephemeral.rs:118-152](taibai_api/src/core/v1/ephemeral.rs:118)）里有，但 **protobuf 编解码经 to_common 转换会丢弃**：`encode_raw`（[ephemeral.rs:414-417](taibai_api/src/core/v1/ephemeral.rs:414)）`message::encode(1, &common)` 只编 common 的 17 字段；`encoded_len_common`（[ephemeral.rs:527+](taibai_api/src/core/v1/ephemeral.rs:527)）亦只覆盖 17 字段；`merge_field` 同。**proto 路径这 8 字段丢失**。
- `PreferAvoidPodsEntry`（Rust [node.rs:598-602](taibai_api/src/core/v1/node.rs:598) 只有 pod_signature）缺 Go（[types.go:6720-6732](kubernetes/staging/src/k8s.io/api/core/v1/types.go:6720)）的 `EvictionTime`（6725）、`Reason`（6728）、`Message`（6731）。internal 版本（[internal/node.rs:212-223](taibai_api/src/core/internal/node.rs:212)）也缺 EvictionTime+Message，且 `PodSignature.pod_controller` 是 `Option<i64>` 而 Go [types.go:6739](kubernetes/staging/src/k8s.io/api/core/v1/types.go:6739) 是 `*metav1.OwnerReference`——**类型错误**。
- `PodSignature`（Rust [node.rs:609-613](taibai_api/src/core/v1/node.rs:609) 的 `pod_signature: String`）——Go 的唯一字段 `PodController *metav1.OwnerReference` 完全没有对应；Rust 的 `pod_signature: String` 是凭空字段。
- `ServiceSpec.ExternalIPs` / `PodLogOptions.InsecureSkipTLSVerifyBackend`：字段存在但 JSON 名错（§5，合并计数）。

**admissionregistration（2 个）**：`Validation.Reason`（Go [types.go:368](kubernetes/staging/src/k8s.io/api/admissionregistration/v1/types.go:368) `Reason *metav1.StatusReason \`json:"reason,omitempty"\``；Rust [v1/mod.rs:580-594](taibai_api/src/admissionregistration/v1/mod.rs:580) 只有 expression/message/message_expression）——v1 + v1alpha1 两处。机器可读的校验失败原因丢失，API 响应降级为无 reason。

**apiextensions（2 个）**：`ConversionRequest.DesiredAPIVersion`（JSON 名错，§5）——v1 + v1beta1。

**附带发现**：
- `NodeSwapStatus`（Rust [node.rs:414-419](taibai_api/src/core/v1/node.rs:414)）无 `Default` derive 且 `capacity: i64` 值字段——Go [types.go:6570-6574](kubernetes/staging/src/k8s.io/api/core/v1/types.go:6570) 是 `Capacity *int64 \`json:"capacity,omitempty"\``，应 `Option<i64>`；
- `ManagedFieldsEntry.fields_v1` 用 `Option<serde_json::Value>` 代替 Go `FieldsV1`（[meta.rs:494-495](taibai_api/src/common/meta.rs:494)）——SSA 核心路径，需专项核对 null/`{}`/缺席语义；
- 3 个无 Default derive 类型（`NodeSwapStatus`/`DaemonEndpoint`/`ConfigMapNodeConfigSource`）不在 zero-marshal 注册表覆盖内（`audit/no_default_types.json`）；`DaemonEndpoint` 的 `Port` 大写 JSON 名正确（Go [types.go:6498](kubernetes/staging/src/k8s.io/api/core/v1/types.go:6498) `Port int32 \`json:"Port"\``；Rust [node.rs:311](taibai_api/src/core/v1/node.rs:311) `#[serde(rename = "Port")]` ✓）。

---

## 5. JSON 字段名错误（8 处，全部实跑验证）— S0

字段存在但 serde 名不对：**decode 时上游键被静默忽略（数据丢失），encode 时以错误键输出**。修复前先在 taibai_api 下创建临时 integration test（`tests/name_bug_check.rs`）实跑：

```
实跑结果（4 个断言全部按预期 FAILED，验证后已清理测试文件）：

test service_external_ips_name_check ... FAILED
  field lost: {"spec":{}}                          ← 输入 {"spec": {"externalIPs": ["1.2.3.4"]}}

test podlog_insecure_name_check ... FAILED
  field lost: {}                                   ← 输入 {"insecureSkipTLSVerifyBackend": true}

test conversion_request_desired_api_version_check ... FAILED
  field lost: {"uid":"u"}                          ← 输入 {"desiredAPIVersion": "v1", "uid": "u"}

test allocated_device_status_share_id_check ... FAILED
  field lost: {"device":"x","driver":"d","pool":"p"}  ← 输入 {..., "shareID": "s"}
```

| # | 位置 | Rust 错误名 | Go 正确名 | Go 证据 | Rust 证据 |
|---|---|---|---|---|---|
| 1 | `ServiceSpec.external_ips` | `externalIps` | `externalIPs` | [types.go:5932](kubernetes/staging/src/k8s.io/api/core/v1/types.go:5932) | [service.rs:322-327](taibai_api/src/core/v1/service.rs:322)（无 rename） |
| 2 | `PodLogOptions.insecure_skip_tls_verify_backend` | `insecureSkipTlsVerifyBackend` | `insecureSkipTLSVerifyBackend` | [types.go:7138](kubernetes/staging/src/k8s.io/api/core/v1/types.go:7138) | [helper.rs:71-73](taibai_api/src/core/v1/helper.rs:71)（无 rename） |
| 3 | `AllocatedDeviceStatus.share_id`（v1） | `shareId` | `shareID` | [types.go:1818](kubernetes/staging/src/k8s.io/api/resource/v1/types.go:1818) | [resource_claim.rs:326-327](taibai_api/src/resource/v1/resource_claim.rs:326) |
| 4 | `AllocatedDeviceStatus.share_id`（v1beta1） | `shareId` | `shareID` | 同上 beta 源 | [resource_claim.rs:288-289](taibai_api/src/resource/v1beta1/resource_claim.rs:288) |
| 5 | `AllocatedDeviceStatus.share_id`（v1beta2） | `shareId` | `shareID` | 同上 beta 源 | [resource_claim.rs:294-295](taibai_api/src/resource/v1beta2/resource_claim.rs:294) |
| 6 | `DeviceRequestAllocationResult.share_id`（v1beta1） | `shareId` | `shareID` | [v1beta1/types.go:1575](kubernetes/staging/src/k8s.io/api/resource/v1beta1/types.go:1575) | [resource_claim.rs:400-401](taibai_api/src/resource/v1beta1/resource_claim.rs:400) |
| 7 | `ConversionRequest.desired_api_version`（v1） | `desiredApiVersion` | `desiredAPIVersion` | [apiextensions/v1/types.go:495](kubernetes/staging/src/k8s.io/apiextensions-apiserver/pkg/apis/apiextensions/v1/types.go:495) | [v1/mod.rs:598-599](taibai_api/src/apiextensions/v1/mod.rs:598)（camelCase 派生） |
| 8 | `ConversionRequest.desired_api_version`（v1beta1） | `desiredApiVersion` | `desiredAPIVersion` | 同上 beta 源 | [v1beta1/mod.rs:621-622](taibai_api/src/apiextensions/v1beta1/mod.rs:621) |

（v1/v1beta2 的 `DeviceRequestAllocationResult.share_id` 属 §4.10 结构性缺失——字段都没有。）

成因：`rename_all = "camelCase"` 遇连续大写缩写（IP/TLS/ID/API）时，Rust 蛇形 `external_ips` → `externalIps`，Go 手写 tag 保留 `externalIPs`。修复：`#[serde(rename = "...")]`（`machineID`/`systemUUID` 已有同类先例，[node.rs:363](taibai_api/src/core/v1/node.rs:363)）。

**业务影响**：
- #1：Service 外部 IP（VIP/负载均衡）**全部丢失**；
- #2：日志请求的 "跳过后端 TLS 校验" 开关丢失（安全相关字段静默失效）；
- #7：**CRD 转换 webhook 请求直接失败**（拿不到目标版本）；
- #3-6：DRA 设备共享标识丢失。

**为什么 wire_compat 没拦住**：`core.v1.Service` fixture 确实含 `"externalIPs"` 键（已抽查 fixture 确认），但 `run_normalized_enum_case`（[mod.rs:312-331](taibai_api/crates/taibai_api_testing/src/wire_compat/mod.rs:312)）断言对象级相等——serde 忽略未知键后丢失发生在 decode 一步，对象比较不可见；`core.v1.PodLogOptions` 在 skip 清单（[core.rs:66-70](taibai_api/crates/taibai_api_testing/src/wire_compat/core.rs:66)）。

**建议**：wire_compat 增加 "decode 后 JSON 键集合 == 上游键集合" 的 shape 断言（`serde_ignored` crate 或 diff 两个 Value 的键路径）。

---

## 6. 未实现 / scope 外（47 类型）

均经 grep 实证，非推测：

1. **networking/v1beta1 Ingress 全家（17 类型）**：`src/networking/v1beta1/` 只有 ip_address.rs 和 service_cidr.rs（各 4 struct），无 Ingress 相关文件。wire_compat 显式声明（[networking.rs:21-22](taibai_api/crates/taibai_api_testing/src/wire_compat/networking.rs:21)）："networking v1beta1 ingress type is not implemented in taibai_api; intentionally out of scope"（Ingress + IngressClass 两 fixture）。
2. **admissionregistration/v1beta1（25 类型）**：`src/admissionregistration/v1beta1/mod.rs` 只有 9 个 struct（ApplyConfiguration/JSONPatch/Mutation/MutatingAdmissionPolicy* 系列）；ValidatingAdmissionPolicy/ValidatingAdmissionPolicyBinding/ValidatingWebhookConfiguration/ValidatingWebhook/MutatingWebhook/WebhookClientConfig/ServiceReference/MatchCondition/ParamKind/ParamRef/MatchResources/Variable/AuditAnnotation/Validation/TypeChecking/ExpressionWarning 等**未 re-export**（mod.rs 头部只有私有 `use crate::admissionregistration::v1::{...}`，无 `pub use`）。wire_compat 声明 4 个 v1beta1 fixture skip。
3. **apimachinery meta/v1（24 类型无对应）**：`grep` `src/common/` 确认存在 14 个（Condition/DeleteOptions/FieldSelectorRequirement/LabelSelector/ListMeta/ManagedFieldsEntry/ObjectMeta/OwnerReference/Preconditions/Status/StatusCause/StatusDetails/TypeMeta/LabelSelectorRequirement）；**不存在 24 个**：APIGroup、APIGroupList、APIResource、APIResourceList、APIVersions、ApplyOptions、CreateOptions、Duration、FieldsV1、GetOptions、GroupVersionForDiscovery、List、ListOptions、PartialObjectMetadata、PartialObjectMetadataList、PatchOptions、RootPaths、ServerAddressByClientCIDR、Table、TableColumnDefinition、TableOptions、TableRow、TableRowCondition、UpdateOptions——发现与 options 类型（影响 `/api`、`/apis` discovery endpoint 实现）。
4. **命名映射而非缺失**：runtime::{TypeMeta,RawExtension,Unknown}、intstr.IntOrString、resource.Quantity 在 common/ 有专门实现（Timestamp、Quantity、IntOrString），不按原名导出。
5. **oneof 建模差异（非缺失）**：`VolumeSource`/`VolumeProjection`/`EnvVarSource` 用 `VolumeSourceRepr` 枚举 + `VolumeSourceFieldsOwned`（[sources.rs:62-105](taibai_api/src/core/v1/volume/sources.rs:62)）承载全部字段——30 个 "缺失" 是提取器视角的假阳性；`IngressRuleValue` 同理（Rust [ingress.rs:165](taibai_api/src/networking/v1/ingress.rs:165) `IngressRuleValueProto` 枚举建模）。
6. **re-export 已确认存在**：authentication/v1beta1::UserInfo、batch/v1beta1::JobTemplateSpec、certificates/v1beta1 2 类型、core/v1::ComponentCondition（在 internal）、StorageVersionStatus、extensions/v1beta1 各类型。

**wire_compat 全部 skip 声明**（grep 实证）：admissionregistration 4、core 20（meta/options 类型 + "legacy volume sources intentionally removed"）、apps 8、extensions 3、batch 1、networking 3（含 v1 Ingress "proto corruption bug"）、storage 3。核心 workload 的 **legacy volume source**（gcePersistentDisk/awsElasticBlockStore 等）被有意移除是**最大的有意范围决策**，若上游真实集群使用这些卷类型，pod 模板经 taibai 转写会丢数据——需产品层确认。

---

## 7. 影响评估（按消费路径）

| 消费路径 | 敏感差异 | 受影响模式 | 严重度 |
|---|---|---|---|
| **热备切换字节恒等**（TEP-0005 核心场景） | 任何 shape 差异 | 全部 P1-P9 | **致命**：切换即漂移，两侧永不收敛 |
| **SSA / managedFields / SMP** | 存在性、null vs 缺席 vs `[]` | P1/P8/P9——SMP 中 null 是删除语义 | **高**：field ownership 误判、patch 计算错误 |
| **ControllerRevision.data**（DS/STS） | 逐字节比较 | P1（template）、P6（25% 污染） | **高**：误判 revision → 滚动重建 |
| **GitOps drift** | 全部 shape 差异 | 全部 | **高**：持续 reconcile |
| **pod-template-hash**（DeepHashObject） | 解码后对象恒等 | P5/P6（虚假默认改变解码对象） | **高**：ReplicaSet/Pod 全量重建 |
| **webhook 生态** | RawExtension null、字段名 | P2、#7 desiredAPIVersion | **高**：CRD 转换直接失败 |
| **CRD 注册面（apiextensions）** | scope/strategy 枚举泄漏、versions 数组缺席 | P5/P8/P4（本轮补全） | **高**：CRD 语义被编造（Namespaced/None） |
| **DRA 调度器** | 结构性缺失 | §4.10 25 个 | **高**（若实现 DRA） |
| **kubectl/client-go 常规读写** | 值语义（decode 宽容） | 除 S0 外多数 | **中**：可用但 `-o json` 不等 |
| **Service/网络面** | #1 externalIPs | §5 | **高**：VIP 丢失 |
| **fuzz/模板/部分字段对象** | 零值路径 | P3/P4/P4b | 中 |

**修复优先级建议**（严重度 × 成本）：

1. **P0**：8 个 JSON 名错误——各一行 `rename`，数据丢失级，半天内可清零；
2. **P0**：DRA 结构性缺失 25 字段（internal 类型已有，向版本化类型同步）+ EphemeralContainerCommon 8 字段（protobuf 路径丢数据）；
3. **P1**：P6/P5 默认值泄漏 57 处（状态污染；`25%`/`Allow`/`Namespaced`/`None` 类需区分 serde Default 与 apiserver defaulting）；
4. **P1**：P1 的 metadata/items 主干（`value_struct_omit` 铺开，机械性强，可脚本辅助）；
5. **P2**：P3/P4/P4b/P8/P9 零值形态 633 处（随 policy 体系批量治理）；
6. **P2**：PreferAvoidPodsEntry、Validation.Reason、List metadata null→`{}` 21 处；
7. **决策项**：§6 范围（networking v1beta1 Ingress、admissionregistration v1beta1、discovery 类型、legacy volume sources）。

---

## 8. 修复策略映射（TEP-0005 代数）

| Go 形态 | taibai 现状 | 应采用 | 代码库既有证据 |
|---|---|---|---|
| 值 struct + omitempty | `Option<T>`+skip | `Option<T>` + `value_struct_omit` | [json_shape.rs:6-40](taibai_api/src/common/json_shape.rs:6)；7 处在用（pod.rs:637 等） |
| `v1.Time` 值 + omitzero/omitempty | `Option<Timestamp>`+skip | `value_struct_omit_zero` | [json_shape.rs:44+](taibai_api/src/common/json_shape.rs:44)；creationTimestamp 已用（[meta.rs:341-355](taibai_api/src/common/meta.rs:341)）✓ 对照组 |
| 无 omitempty string/int/bool | skip 或 Option+skip | 去 skip（值字段）或零标量 policy | `value_scalar_omit::is_none_or_zero_i32/i64`（[json_shape.rs:131](taibai_api/src/common/json_shape.rs:131)），字符串版需补 |
| 无 omitempty slice → null | `Vec`+skip 或输出 `[]` | `Option<Vec>` 或 emit-null policy | **需新增** `slice_null_emit` |
| 无 omitempty 指针/RawExtension → null | `Option`+skip | 去 skip（serde Option None 默认序列化 null，零成本） | 无需新 policy |
| 字符串枚举（`type X string`） | 裸 enum+`#[default]` | `String` 或无默认 enum+`""` | 逐案 |
| apiserver 默认值（25%/Allow） | serde Default 泄漏 | 挪到 defaulting 函数 | k8s 语义：defaulting 独立阶段 |
| 缩写命名（IP/TLS/ID/API） | camelCase 派生 | 手写 `rename` | machineID/systemUUID/bootID 先例（[node.rs:363-370](taibai_api/src/core/v1/node.rs:363)） |

---

## 9. 审计产物清单（可复现）

| 文件 | 内容 |
|---|---|
| `audit/findings_table.json` | 1142 行机器可读表（pattern/gv/struct/field/go_omitempty/go_type/rust_type/go_wire/rust_wire） |
| `audit/appendix_by_pattern.json` | 按模式分组的去重清单 |
| `audit/missing_fields_final.json` | 34 个结构性缺失字段 |
| `audit/findings_by_pattern.json` | 按模式分组原始行 |
| `audit/findings_new_groups.json` | 覆盖补全产生的 68 行（apiextensions/apiregistration；另有 4 行 SubresourceScale 实跑补录在 findings_table.json） |
| `audit/go_types.json` / `rust_types.json` | 静态提取产物（Go 1191 / Rust 1149 struct） |
| `audit/go_zero_full.json` / `rust_zero_full.json` | 零值 ground truth（Go 反射 1187 / Rust Default 1131 类型） |
| `audit/gozerogen/registry.go` | Go 反射零值序列化注册表（含 `registry2()`：apiextensions-apiserver + kube-aggregator staging 仓库） |
| `audit/extract_go.py` / `extract_rust.py`（v3） | 静态提取器 |
| `audit/no_default_types.json` | 无 Default derive 的 3 类型 |

复现路径：`extract_rust.py` → `compare_zero.py`（三层交叉）→ `classify_scope.py`（scope-out 分类）→ 人工复核（本报告全部证据行号）。

---

## 10. 结论

taibai_api 在**值语义**层面（非零数据读写往返）与 K8s v1.34.1 高度兼容——849 个 wire_compat 用例全绿佐证。但在三个维度存在系统性缺口：

1. **JSON 形态**（零值字段存在性、null 语义、空容器形态）：633 + 452 = 1085 处，占 95%——TEP-0005 policy 代数已就绪且有生产先例（creationTimestamp、kubeProxyVersion 修复样板），缺的是按清单铺开；
2. **字段覆盖**：8 个命名错误（一行 rename，数据丢失级）+ 34 个缺失字段（DRA 1.34 新特性为主，internal 类型已有可同步）；
3. **默认值语义**：57 处泄漏，其中 `25%`/`Allow`/`Namespaced`/`None` 类属**状态污染**（serde Default 越权承担了 apiserver defaulting 职责）——本轮覆盖补全后，apiextensions 的 CRD 枚举泄漏是其中语义后果最重的一类。

真正的产品决策点是 §6：networking v1beta1 Ingress、admissionregistration v1beta1 Validating*、discovery/options 类型、以及**legacy volume sources 的有意移除**（若上游集群使用 gcePersistentDisk 等卷类型，pod 模板经 taibai 转写会丢数据）是否入 roadmap。

---

## 附录 A：P1 metadata 缺输出的 163 个顶层资源类型（按 GV）

admissionregistration/v1: MutatingWebhookConfiguration, ValidatingAdmissionPolicy, ValidatingAdmissionPolicyBinding, ValidatingWebhookConfiguration · v1alpha1: MutatingAdmissionPolicy, MutatingAdmissionPolicyBinding, ValidatingAdmissionPolicy, ValidatingAdmissionPolicyBinding
apidiscovery/v2 + v2beta1: APIGroupDiscovery
apiextensions/v1 + v1beta1: CustomResourceDefinition（本轮覆盖补全）
apiserverinternal/v1alpha1: StorageVersion
apiregistration/v1 + v1beta1: APIService（本轮覆盖补全）
apps/v1: ControllerRevision, DaemonSet, Deployment, ReplicaSet, StatefulSet · v1beta1: ControllerRevision, Deployment, Scale, StatefulSet · v1beta2: ControllerRevision, DaemonSet, Deployment, ReplicaSet, Scale, StatefulSet
authentication/v1: SelfSubjectReview, TokenRequest, TokenReview · v1alpha1: SelfSubjectReview · v1beta1: SelfSubjectReview, TokenReview
authorization/v1 + v1beta1: LocalSubjectAccessReview, SelfSubjectAccessReview, SelfSubjectRulesReview, SubjectAccessReview
autoscaling/v1: HorizontalPodAutoscaler, Scale · v2/v2beta1/v2beta2: HorizontalPodAutoscaler
batch/v1: CronJob, Job, JobTemplateSpec · v1beta1: CronJob
certificates/v1: CertificateSigningRequest · v1alpha1: ClusterTrustBundle, PodCertificateRequest · v1beta1: CertificateSigningRequest, ClusterTrustBundle
coordination/v1: Lease · v1alpha2: LeaseCandidate · v1beta1: Lease, LeaseCandidate
core/v1: Binding, ComponentStatus, ConfigMap, Endpoints, Event, LimitRange, Namespace, Node, PersistentVolume, PersistentVolumeClaim, PersistentVolumeClaimTemplate, Pod, PodStatusResult, PodTemplate, PodTemplateSpec, RangeAllocation, ReplicationController, ResourceQuota, Secret, Service, ServiceAccount
discovery/v1 + v1beta1: EndpointSlice
events/v1 + v1beta1: Event
extensions/v1beta1: DaemonSet, Deployment, Ingress, NetworkPolicy, ReplicaSet, Scale
flowcontrol/v1 + v1beta1 + v1beta2 + v1beta3: FlowSchema, PriorityLevelConfiguration
imagepolicy/v1alpha1: ImageReview
networking/v1: IPAddress, Ingress, IngressClass, NetworkPolicy, ServiceCIDR · v1beta1: IPAddress, ServiceCIDR
node/v1 + v1alpha1 + v1beta1: RuntimeClass
policy/v1 + v1beta1: Eviction, PodDisruptionBudget
rbac/v1 + v1alpha1 + v1beta1: ClusterRole, ClusterRoleBinding, Role, RoleBinding
resource/v1 + v1beta1 + v1beta2: DeviceClass, ResourceClaim, ResourceClaimTemplate, ResourceClaimTemplateSpec, ResourceSlice · v1alpha3: DeviceTaintRule
scheduling/v1 + v1alpha1 + v1beta1: PriorityClass
storage/v1: CSIDriver, CSINode, CSIStorageCapacity, StorageClass, VolumeAttachment, VolumeAttributesClass · v1alpha1: CSIStorageCapacity, VolumeAttachment, VolumeAttributesClass · v1beta1: CSIDriver, CSINode, CSIStorageCapacity, StorageClass, VolumeAttachment, VolumeAttributesClass
storagemigration/v1alpha1: StorageVersionMigration

（另有 112 个 List 类型的 metadata 同型缺失——本轮含 `CustomResourceDefinitionList`、`APIServiceList` 各 2 版本——完整清单见 `findings_table.json` 按 `field=="metadata" & struct endswith "List"` 过滤。）

## 附录 B：P4 全部 137 个唯一字段对 / P8 全部 98 对 / P9 全部 44 对 / P3 全部 35 对 / P4b 全部 18 对 / P5 全部 13 对 / P6 全部 16 对

见 `audit/appendix_by_pattern.json`（本报告 §4 各节已列分布与代表字段；机器可读全量以该文件为准，每行格式 `gv::struct.field  Go=<wire> → Rust=<wire>`）。

## 附录 C：实跑验证记录

- §5 的 4 个失败断言：在 taibai_api 下临时创建 `tests/name_bug_check.rs` 运行（`cargo test --test name_bug_check`），输出原文已嵌入 §5 开头代码块，验证后已删除测试文件；
- §3 / §4 各零值对照：`audit/go_zero_full.json` 与 `audit/rust_zero_full.json` 的对应键（如 `core/v1::Pod`、`rbac/v1::ClusterRole`、`resource/v1::DeviceConstraint`）；
- wire_compat 基线：`cargo test -p taibai_api_testing` → **849 passed; 0 failed; 1 ignored**（本轮实跑确认）；
- Node fixture 零值缺失证据：`crates/taibai_api_testing/testdata/v1.33.0/core.v1.Node.json` 的 nodeInfo 全部字段为 `"xxxValue"` 非零值；
- §4.2 `CustomResourceSubresourceScale`：临时可执行 crate 实跑 `serde_json::to_value(T::default())`，v1 与 v1beta1 均输出 `{}`（Go 侧 `go_zero_full.json` 为 `{"specReplicasPath":"","statusReplicasPath":""}`），验证后已清理；
- 覆盖补全回归：`gozerogen` 重建（`go build` + 运行）→ `go_zero_full.json` 1136→1187 类型；`compare_zero.py` 重跑 → 1263→1284 原始发现；apiextensions/apiregistration 72 行经 `findings_new_groups.json` 分类后并入 `findings_table.json`。
