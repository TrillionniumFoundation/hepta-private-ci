# 完整 Agentd 集成编译的实际可行性

## 当前结论

现有恢复 checkout 和本实验配置的 dependency cache **不足以执行完整目标 Agentd 编译**。实际运行 `cargo metadata --offline --no-deps` 在读取 workspace member manifest 时就失败，尚未进入 Agentd 或新增 loader 的编译。因此这里记录的是**checkout/依赖材料与环境能力缺口**；不是 CI 失败，不是编译器已经证明该 patch 有错，也不是 native 产品调用的 `OwnerEvidence(Unavailable)` authority 拒绝。

已完成的真实范围是：原 journal API 上的完整段链 helper 编译/21 项验证；以及针对精确 patched serde 声明的 15 项 JSON/表示选择验证。没有把简化的 `AgentdRuntime`、`AgentdIdentity` 或 `AgentdError` 替身作为完整 loader 的编译证据。没有启动大规模 workspace 构建或依赖下载。

## 1. 精确目标与本地源身份

目标 commit 为 [`f8c9419df6ddeb36ff8b522a50219981fb8d9345`](https://github.com/TrillionniumFoundation/hepta-private-ci/tree/f8c9419df6ddeb36ff8b522a50219981fb8d9345)。以下文件已经从该 ref 只读核对，Git blob 身份保存在 [INTEGRATION_ENVIRONMENT.json](INTEGRATION_ENVIRONMENT.json)。

| 文件 | 目标 Git blob | 当前工作树情况 |
| --- | --- | --- |
| `codex-rs/Cargo.toml` | `d2703b590935ab17316e6c258657c0ce5ab7412a` | 本地 byte identity 相同 |
| `hepta-agentd/Cargo.toml` | `5d13cd8f355bab3ecb95f8c068517de200dd143f` | 本地 byte identity 相同 |
| `hepta-agentd/src/lib.rs` | `c075e561eaa96820706ad98d20972eb5fd924b06` | 本地缺少入口文件；已只读目标模块声明 |
| `plasticity_process_bootstrap.rs` | `f44c8858a55886c7997562a02ba87b9a7d359bf2` | 本地产品目录缺少；独立 exact-base cache/patch 已保留 |
| `plasticity_host.rs` | `085d85fde32b89d59eb3169d8d8f6e7f005c2ac5` | 本地原 owner bridge 使用相同字节 |
| `plasticity_owner_evidence.rs` | `c3db02b42db094556889774b40306198292dc27e` | 本地原 owner bridge 使用相同字节 |
| `plasticity_anchor_journal.rs` | `cb2c3ae9bbb75c067c7745e82c33cded0e241baa` | 本地原 owner bridge 使用相同字节 |
| `plasticity_runtime.rs` | `d1c57448d9c344171ae85d0abe888fe990e7a021` | 本地文件相同；完整运行依赖未物化 |
| `topology_plasticity_host.rs` | `a21aeb28e95cfaf19c1440ee4f32584f07c6ce36` | 只读目标源码，不在既有小 owner bridge 中 |

本地还缺 `hepta-agentd/src/main.rs`。普通 Git 读取目标对象时触发 lazy fetch，实际在连接配置的 `browser-proxy:8889` 时失败；选定文件通过已有 GitHub connector 只读取得。这不是完整目标 tree 已经 checkout 成功。

本轮实际已编译研究 kernel/依赖仍固定在 `9595221c21f1fe0775295a9c8756a1ba4d69ea49`，不因若干 Agentd 文件与新 ref 相同而自动成为整个 `f8c9419` 的产品构建。

## 2. 当前 workspace、缓存和实际第一失败

按 byte-exact 的两个 Cargo manifest 解析，Agentd 有 **41 个直接 path dependency**；本地存在其中 16 个 manifest，缺少 25 个。这还没有计算其完整传递闭包。缺失项为：

| 类别 | 缺失的直接 package |
| --- | --- |
| App Server / 通用运行 | `codex-app-server`, `codex-app-server-client`, `codex-app-server-protocol`, `codex-arg0`, `codex-config`, `codex-features`, `codex-model-provider`, `codex-protocol`, `codex-state`, `codex-uds` |
| Hepta 运行组合 | `codex-hepta-agent-protocol`, `codex-hepta-automation`, `codex-hepta-bellman-operator`, `codex-hepta-authbus`, `codex-hepta-evidence`, `codex-hepta-codex-adapter`, `codex-hepta-cognitive-store`, `codex-hepta-control-plane`, `codex-hepta-fleet`, `codex-hepta-memory`, `codex-hepta-memory-extension`, `codex-hepta-paths` |
| 工具 crate | `codex-utils-absolute-path`, `codex-utils-cli`, `codex-utils-home-dir` |

实际命令使用已安装 Rust 1.95.0 的 Cargo，以及本轮 CARGO_HOME：

```bash
CARGO_HOME=/workspace/scratch/2b3c256bef7d/abc3-native-runs/cargo-home \
  /workspace/scratch/2b3c256bef7d/task-tools/rust-1.95.0/bin/cargo \
  metadata --offline --no-deps --format-version=1 \
  --manifest-path codex-rs/Cargo.toml
```

cwd 为 `/workspace/scratch/2b3c256bef7d/hepta-ndu-recovery`，实际 exit **101**，第一错误是：

```text
failed to load manifest for workspace member .../codex-rs/aws-auth
failed to read .../codex-rs/aws-auth/Cargo.toml
No such file or directory (os error 2)
```

即使只计划 `-p codex-hepta-agentd`，原 workspace 的 member 读取仍需要先完整；不能把上述错误改称 Agentd compile error。也没有据此声称每一个后续 dependency 或全部工程检查都已失败。

当前指定 CARGO_HOME 只有 **51 个已解包 registry package**，release target 有 **55 个 rlib**；没有 `tokio`、`mio`、`socket2` 或 `futures` 族的 source package。缓存足够支持已经验证的同步原 native 切片，无法据此满足 App Server、async runtime 和其余产品依赖。审计记录时可用空间为 **1,451,151,360 B，约 1.35 GiB**；完整传递闭包尚未成功解析，不能给出已经验证的完整 build 空间上界。

## 3. 最小可编译单元与边界

已有 `neuron_chain_recovery.rs` 只依赖原 `codex-hepta-neuron`、基础类型和 serde，能直接链接已构建 release rlib。它和真实13段副本的21项 probe 已经完成，详见 [README.md](README.md) 和 [CHAIN_RECOVERY_VALIDATION.json](CHAIN_RECOVERY_VALIDATION.json)。

完整 process loader 的主体虽是同步文件读取与验证，但直接连接真实产品类型：

- `AgentdIdentity` 来自真实 config，含 Fleet/Path 的 layout、resource 类型；loader 当前读取其实际 `agent_id` 和 `spawn_generation`。
- `AgentdError` 的原 enum 还绑定 automation、fleet、memory、cognitive-store 的错误类型。
- `PlasticityRuntimeBootstrapV1` 是真实长期 owner envelope；其模块继续连接 Tokio channel、`AgentdState`、parameter/topology writer 与 runtime composition。
- `topology_plasticity_host` 需要真实 topology owner、registry 和独立 anchor 组合；并非仅给一个同名方法即可替代。

理论上可以另做生产分层，把纯 loader materials 从这些 host 类型中提取为独立组件，再让原 Agentd envelope 显式消费它。但那将是新的约900行源组织重构、独立 API 及新的集成风险，仍不能替代完整目标 daemon 的验证。本轮按既定范围没有开展这项重构，也没有以 stub 让原 loader “编译通过”。

## 4. 已额外验证的真实 serde 风险

`descriptor_probe.py` 从已经通过 exact-base apply 检查的目标 patched source 中，逐字节提取 `InhibitoryEdgeDescriptorV1`、`SparseConfigDescriptorV1`、`NeuronDescriptorV1` 三个真实 declaration；源码片段 SHA 为 `4ba9b0d98816ecd1e5cf743fadf263907dca52e2e84f549474fe3211ac088299`。它链接原 chain helper，不替换任何 loader、runtime 或错误类型。

一次单 CPU 小 binary 实际完成 **15 项**检查：4项正常 single/chain JSON及null表示检查，11项冲突、空chain、缺capacity、单独capacity、unknown字段、非法usize、错误类型和缺required字段拒绝。JSON重新编码后再按原 typed declaration 解码，selected path/capacity 列表一致。[DESCRIPTOR_SERDE_VALIDATION.json](DESCRIPTOR_SERDE_VALIDATION.json)

一个应明确的接口细节是：Serde 的 `Option` 会把省略字段和显式 JSON `null` 都解析为 `None`。因此新chain可以带 `journal_path:null,max_records:null`，旧single可以带 `segment_chain:null`；**两个非空实际表示仍拒绝，空数组 `[]` 也仍是真实 `Some(empty)` 并被拒绝**。README 的“省略另一种表示”是推荐写法，不应误读为实现会拒绝等价的显式null。这个检查没有修改helper或已发布patch。

完整 exact-child receipt 为 **1.689851 s wall、1.680333 s CPU、peak RSS202,870,784 B**；内部编译+probe计时1.645201s。见 [DESCRIPTOR_SERDE_PROCESS_RECEIPT.json](DESCRIPTOR_SERDE_PROCESS_RECEIPT.json)。没有读取journal、打开新科学来源、生成owner/signature资格、调用原完整loader或累计额外统计N。测试字符串刻意标为`not-authority`，不能构成有效生产bundle。

## 5. 真正完整集成的下一份工程输入

需要首先取得目标 `f8c9419` 的完整 workspace/source tree（含原 member manifests、Agentd lib/main及所有实际依赖），匹配的 lock/toolchain 与完整 registry/git dependency cache，以及足够的可用构建空间。随后对 exact-base 应用本补丁，在独立目标目录先完成真实 metadata、再进行限定 package 的 `cargo check -p codex-hepta-agentd` 和必要的 Agentd descriptor/owner 组合测试。资源成本应重新测量，不能从小helper推算全daemon。

首次真实 loader 运行还应使用现有部署 owner 提供的 descriptor、独立 acknowledged stores/witness、真实 Dataset receipt 和信任/角色签署来源。缺少这些材料时应保留实际第一拒绝，不用测试身份构造一次假生产成功。完整 workspace 的工程验证与正式 authority 的运行资格是两条分别需要真实证据的链，本轮均未假定已经通过。
