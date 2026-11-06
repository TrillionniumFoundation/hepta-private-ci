# SQLx 0.9.0 native lifetime token：完整源码接入与验收入口

## 当前结论

完整发布包已只读取回并核验，静态源码接入可复现。**依赖解析、编译、锁生成、原生测试和产品平台资格仍未执行。** 这份交付不把 B16 的 Current、Root、最终使用授权或整个恢复链标为完成。

原始输入是实际 ROG registry 缓存中的 sqlx-sqlite 0.9.0，而非从版本标签推断出来的包：93,440 B，SHA256 `488e99c397a62007e4229aec669a179816339afc6d2620ca6fa420dbee2e982c`，VCS `003b698e99e024f3621b8043a2426fde5b741171`。两次 binary_read 分别读取 65,536 B 和 27,904 B，第二次固定第一次返回的版本；每段及整包均独立重算哈希。未启动任何原生进程，也未修改原生 source、target、cache 或 ref。

## 固定交付

| 内容 | 不可达 Git blob | 范围 |
| --- | --- | --- |
| 原始二进制 crate | `ba066c6090be2051481fb746326fcc2017dd8de4` | 完整原包，不是源码摘要 |
| 原始两段 base64 及版本 | `934efbb47cafb2b6b16b16257c4d4424b0ff4647` | 可在不重新读取 native 的情况下恢复原包 |
| 原包完整成员清单 | `13d34ce4a9059fd8cbdc3bd47228cf1ec9ed1a34` | 57 个 regular 文件，407,888 B，逐项原模式及哈希 |
| 完整 vendor 源码 payload | `ed4b2ade11ac009426131347a127419a179fcf73` | 60 个文件，469,133 B JSON，全部正文、模式及哈希 |
| 完整静态重建收据 | `2193443e1cbbd2017ba56d036f863f80cc2b187f` | 60 个 vendor 文件加 root Cargo，共 61 个精确后像 |
| 驱动功能补丁 | `abe067bc6f2ca9601eef83b0cd4e0db4811827ac` | 5 个路径；4 个父控制与 ignored support 分列 |
| Cargo / BUILD 接入补丁 | `0c7c5f3d6cb45cec4a10a64855242ddc22e35eb7` | 3 个路径，23 加 / 1 删 |
| 许可证机械 overlay | `f62e4cefff604511dec34d1e2edd103863eb2b90` | 同一固定 VCS 根目录的两份完整文本 |

完整机器清单为本目录的 `adoption-manifest-v2.json`。之前尚未取得全包时的清单保留为 `adoption-manifest.pre-archive.json`，没有改写历史。

### 原包和 vendor 的明确差异

57 个原包成员中有 51 份 Rust 源码；其 366,610 B 正文全部逐项等于固定 Git 完整树。原包的 LICENSE-APACHE 与 LICENSE-MIT 实际是 17 B / 14 B 的普通转引文件，正文分别为 `../LICENSE-APACHE`、`../LICENSE-MIT`。此前“发布包必有完整许可证文本”的检查在写入前拒绝，失败保留在 `ebc725c364b790adc432a10454ef4b5a7f612b16`。

原包本身完整保留。产品 vendor 副本另外做两项机械处理：

- 将两份转引替换为同一 `003b698e` 根目录的完整许可证，正文 blob 分别为 `e14699fb149e0b5cd2f2aa206d7bc4d5f8828fc3` 和 `6fe828e8eab3262db2dd59e567e3b35d8aea0f66`。
- 将所有 regular 文件统一为 Git mode 100644；原包中 54 个 0755 文件因此发生纯模式规范化。源文件不获得执行含义，原模式继续留在完整成员清单。

五份驱动后像、三份 scaffold 后像仍各自精确。驱动与 scaffold 合计 500 行变动；完整上游文件、许可证文本和模式规范化均是独立标识的机械导入，不混称新增功能逻辑。原包内的 Cargo.lock 作为上游发布内容保留；真正的 workspace lock 仍是 codex-rs/Cargo.lock。

## 为什么需要这三个接入改动

当前实际完整 A metadata 中，sqlx-sqlite 0.9.0 是 registry dependency，不是 workspace member。仅运行产品 crate 的 `--lib` 不会运行这个依赖自己的单元测试。

1. root Cargo 显式添加 `third_party/sqlx-sqlite-0.9.0` member，并在 root `[patch.crates-io]` 选择同版本的真实本地源。
2. 原始规范化驱动 Cargo.toml 的空 dev-dependencies 表改为精确 `sqlx-core =0.9.0`、feature `_rt-tokio`，为驱动自己的控制提供真实 runtime。原 normal dependency 和 public default features 不变。
3. 新 BUILD 复用现有 `codex_rust_crate`，显式 edition 2021 与实际 A 图中的八个 driver features，提供库和自身 unit target。

Cargo source patch 对所有解析到同一 0.9.0 的消费者生效；它不是只影响 state 二进制。只有调用方显式设置 token 时才启用新的资源持有行为；原 token=None 路径、SQLite 后端、版本与权限没有因此被替换。

## 唯一原生通道的后续顺序

A 完成并冻结后，先复核当前 root Cargo 仍与本补丁前像一致。若 A 有依赖变更，先做明确的源差异对齐，不覆盖它。完整源码 payload 可以直接提供后像，也可以按原包、驱动补丁、scaffold、许可证 overlay 依次重建。

在 codex-rs 中执行真实正常解析：

```bash
cargo metadata --format-version=1
```

必须观察到唯一选中的 sqlx-sqlite 0.9.0 是批准路径中的本地包、source=None，并且 package id 真正属于 workspace_members。检查原生成的 Cargo.lock 和实际 dependency / runtime / native SQLite links 关系，不接受 unused patch 或同时选中未解释的 registry 副本。

然后按原仓库入口运行：

```bash
just bazel-lock-update
just bazel-lock-check
```

保留真实 Cargo.lock 与 MODULE.bazel.lock 结果，无论是否产生 diff；不手写锁、不预设必然无变化。还须检查生成的 @crates DEP_DATA 有 vendor package key 及真实 normal/dev dependencies。静态 BUILD 不能替代这一步。

原八个 driver features 为：

```text
bundled,chrono,json,migrate,offline,serde,time,uuid
```

实际 catalog 入口：

```bash
cargo nextest list -p sqlx-sqlite --lib --locked \
  --features bundled,chrono,json,migrate,offline,serde,time,uuid \
  --message-format json
```

原单位测试入口：

```bash
just test -p sqlx-sqlite --lib --locked --retries 0 \
  --features bundled,chrono,json,migrate,offline,serde,time,uuid
```

通过原 macro 对应的 Bazel target：

```text
//codex-rs/third_party/sqlx-sqlite-0.9.0:sqlx-sqlite-unit-tests
```

Bazel 必须沿用真实原平台/config 入口；不改 wrapper、filter、重试、超时、平台例外或 no-tests 规则。最终执行原 just fix / just fmt 和所需生成锁门。

## 精确的 12 个父用例

以下名单是源检查得出的预期，实际 native catalog 必须逐名匹配；不能用数量相同替代名单相同。

原有 8 个：

```text
connection::explain::test_explain
connection::explain::test_root_block_columns_has_types
options::parse::it_returns_the_parsed_url
options::parse::test_parse_in_memory
options::parse::test_parse_read_only
options::parse::test_parse_shared_in_memory
testing::test_convert_path
type_info::test_data_type_from_str
```

新增 4 个：

```text
options::connection_lifetime::tests::cancellation_during_native_open_keeps_resource_custody
options::connection_lifetime::tests::cancellation_during_initial_pragmas_keeps_resource_custody
options::connection_lifetime::tests::pool_growth_and_cancelled_close_keep_borrowed_connection_custody
options::connection_lifetime::tests::initialization_error_releases_but_failed_native_close_retains_custody
```

`options::connection_lifetime::tests::owned_scenario` 是由父用例明确调用的 ignored support，不是第 13 个 PASS。原四个 regexp 测试由本次未启用的 regexp feature 控制，不能冒称已覆盖 all-features 或上游 facade integration。

先按驱动 manifest `9262807373267fe42587a36a50721aa08b60c56b` 执行两组原始反事实，再精确恢复，最后运行全部 12 例：

- 去掉 worker token 的反事实选择前两个取消用例。必须先进入真正 native callback，再观察真实第二进程锁探测和 gate 状态；普通 timeout 或任意失败不构成因果证明。
- 错误 close 释放 token 的反事实选择第四个用例。必须实际观察 BUSY 路径、原 WorkerCrashed / ROW 约束和锁状态，不能用单纯布尔或 panic 代替。
- 每次 negative / restore 都核完整选中源码后像，保存新鲜原 raw / JUnit、确切父名单、binary 和源码身份。

失败 native close 的生产行为是保留 token 并维持原 panic；这会有意持有资源直到进程退出。正常成功 close 后才释放。调用方自行保留 Arc 或形成循环可能延长持有；它们没有被包装成 Current 权威证明。

## 与 B 基础和实际调用方的分账

| 独立阶段 | 预期新控制数 | 当前状态 |
| --- | ---: | --- |
| 驱动自身 | 4，另保原 8 例 | 静态完成，尚未编译/执行 |
| R2c/d/e1/e2a/e2b/e3 冻结 B 序列 | 24 | 仍按 `a46fdc65f78295bfb041732aeb03b1937f85eab9` 分阶段执行 |
| state / Memory 实际 token 绑定 | 2 state + 1 Memory | 另有原负控、恢复和 owning gate，不并入前两项 |

state 已有 libsqlite3-sys、sqlx 与所需 Tokio features，原 BUILD 的 src/**/*.rs 会包含新测试模块，无需为该调用方额外增加依赖。其两个 state 控制实际包含 temporary runtime shutdown 后取消，不能额外声称证明 runtime 仍活着的取消场景。父 fixture 只保留 child checkpoint stdout，其他 child stdout 被丢弃、stderr 继承；不声称保留完整 child stdout。

两个显式 pool 绑定之外，`checkpoint_private_recovery_database` 的直接 options.connect 仍是单独追踪的缺口，研究代理正在准备下一独立片段。没有把它、独立未 opt-in 连接、Current 授权、期限/撤销或最终使用边界升级为完成。
