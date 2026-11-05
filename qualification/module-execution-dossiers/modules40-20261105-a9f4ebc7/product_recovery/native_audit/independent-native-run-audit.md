# 四包原生测试独立审计

**Run2 的实际运行结果已独立确认：697 个执行测试全部通过，59 个关键测试逐名通过；全套仍有 66 项跳过。** 原始入口退出码为 0，运行过程中没有失败重试或 flaky 结果。第一次运行的失败、重试和缺失原生 JUnit 的事实均保留。

测试源码固定为 `58c81ccdd25002ae0f481d434af067a56fa7ddb8`，tree 为 `57809be09ef01c02389ef37a817f1447d13d167b`。后续导航或元数据提交不能替换这次 Rust 测试的源码身份。

## 两次原始运行

| 运行 | 原始入口退出码 | 实际执行 | 通过 | 失败 | 慢测试 | 全套跳过 | 原生 JUnit |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | --- |
| Run1 | 100 | 697 | 696 | 1 | 1 | 66 | 未生成 |
| Run2 | 0 | 697 | 697 | 0 | 1 | 66 | 697 个实际运行 case，21 个 suite |

两次日志里的实际选中测试集合逐名相等，均为 697 项、21 个二进制。Run2 的 697 个唯一 `PASS` 身份与原生 XML 中的 697 个唯一 case 身份完全相等；XML UUID、时间区间、耗时、字节数和 SHA-256 与原始运行记录相符。

Run1 的唯一失败是 `codex-hepta-infer-worker-host` 中的 `native_app_server::tests::real_agentd_worker_accepts_fresh_context_and_rejects_final_use_tombstone`。第一次执行和原 profile 允许的一次重试都在 `probe existing agentd control socket` 阶段遇到 `InvalidInput: path must be shorter than SUN_LEN`；两条实际控制 socket 路径均为 140 字节。失败发生在宿主初始化期间，尚未进入该测试的 fresh-context/tombstone 断言。它仍作为一次实际失败记录，不能因为后来通过而抹去。

Run1 的 receipt 明确记录 `fresh_junit=[]`，因此没有 Run1 的 59 项 XML 审计，也没有把 stdout 转写成替代 XML。

## Run2 的明确变更

源码、四个包、`local` profile、筛选、重试、超时和断言保持原条件。Run2 将独立私有 `TMPDIR` 缩短为 `/tmp/a9f4ebc7`，并在原 `just test --locked -p …` 入口后追加两个已记录的参数：外部 report-only 配置和现成 Cargo metadata 文件。命令字符串并非与 Run1 字面完全相同。

外部 TOML 原件逐字节等于 receipt 中的内容，仅包含 `[profile.local.junit]` 下的绝对 `path`，没有测试选择或预算配置。metadata 使用原 wrapper 的 scoped 命令 `cargo metadata --no-deps --format-version=1 --locked`，从相同源码的 `codex-rs` 执行。独立读取原 wrapper 后确认，两组参数解析出相同四包，且 filtersets 均为空；实际 697 项测试集合一致也提供了运行层面的交叉核对。

补齐的 metadata 原始 JSON 为 942,439 字节，SHA-256 为 `46c44dc18560eee9f3ecc3ab72a4b7389b61a637b4c9b924210c377f61e3f988`，与 Run2 receipt 完全一致。原生 gzip 为 39,141 字节，SHA-256 为 `8eb27b634b1f93bb059e45591cc8bb585abf7f06524679c161cf0417879da2b5`，解压后与 JSON 原件逐字节相等；独立 metadata receipt 也与 Run2 内嵌记录相同。

metadata 的 `workspace_root` 指向固定测试工作树的 `source/codex-rs`，`target_directory` 与记录的 `CARGO_TARGET_DIR` 相符。它包含 193 个 workspace 成员，`resolve=null`，符合该次 `--no-deps` 输出；四个 `-p` 指定包各出现一次，均属于同一工作树。metadata 中这四包的 21 个启用测试目标与实际 JUnit 的 21 个 suite 完全相等，59 项关键测试对应的二进制均启用。193 个 workspace 成员不是本次测试的包选择范围，实际仍由原命令限定四包。此次补审只读取原件，没有重新执行 Cargo 或 Rust 测试。

此前“`local` 自动继承 `default.junit.path`”的判断已被更正。固定 `cargo-nextest 0.9.103` 源码表明：存在自定义 local profile 时，其空 JUnit path 遮蔽 default path。Run2 使用该版本支持的原生报告参数实际生成 XML；没有修改仓库 profile 或原 wrapper。版本源码、配置和行为解释见 [native-run-environment-and-reporting-review.md](../native-run-environment-and-reporting-review.md)。

## 关键测试与源码绑定

| 包 | 必须逐名通过的测试 |
| --- | ---: |
| `codex-hepta-agent-protocol` | 3 |
| `codex-hepta-agentd` | 13 |
| `codex-hepta-infer-worker-host` | 40 |
| `codex-hepta-runtime` | 3 |
| 合计 | 59 |

59 项由不可变原 49 项和 e65 主线新增 10 项组成。审计确认原 49 项逐字段保留，59 项的完整模块名、目标二进制和 required 标志不变；每项都恰好出现一次，目标不混淆，没有 missing、skip、失败、重复或 flaky/retry。

覆盖的关键条件包括 bound snapshot/ABA、canonical identity 与 generation、原 deadline 上限、Desktop 原 issuer/writer 联合边界、worker 持久终态与 Agentd ACK 之间的进程崩溃、真实 thread/read 恢复、owner loss/timeout、原 public runtime 拒绝入口，以及 10 项 terminal message 合并和输出上限回归。

17 个关键测试源码文件已从审过的 C0 staged 内容、e65 三方解决方案和实际 formatter patch 独立重建，字节数、SHA-256、Git blob ID 全部与执行清单一致。另从 GitHub 固定 C58 tree 读取并核对 17 个源码文件及 11 个运行上下文文件，28 个 blob 全部匹配。实际 wrapper 和 nextest 配置字节也与该清单吻合。两次 receipt 都绑定同一执行清单和 C58/tree；Run2 明确记录执行前后 tracked status 为空。Run1 记录末态为空，但没有单独的 `source_status_before` 字段，本审计不补造该观测。

未修改的 JUnit checker 在此前本地独立复跑退出 0，其语义结果与原生侧 checker 一致。补齐 metadata 原件后，独立综合审计通过 59/59 项一致性检查；这不是再运行一次 Rust suite，也不把 build、fmt、Clippy 或 source binder 当作测试通过。

## 结论范围

原生 XML 只含 697 个运行 case，因此 checker 输出中的 `0 skips` 仅描述 XML 内部，不表示全套零跳过。**全套 66 项 skipped 必须始终随通过结果一并报告**；现有 XML 不提供这 66 项的名称或原因。

恢复进程测试的范围是重启 worker，原 Agentd/App Server 仍存活。它们没有验收 Agentd 协调器自身重启、跨 owner 接管、真实加速器/provider 容量，或 40 个模块的全部生产闭环。intelligence request fingerprint 从 v2 到 v3 后会拒绝不兼容的旧 journal，没有建立透明旧格式迁移路径。JUnit 本身也不能证明测试内部没有提前返回；这部分依赖已审过的原生进程完成标记和断言。

## 原始证据与复核输出

- [independent-native-run-audit.json](independent-native-run-audit.json)：59 项检查、两次运行事实、全部输入文件 SHA-256 和限制。
- [run2-independent-junit.json](run2-independent-junit.json)：59 项完整测试名、精确目标和逐项结果。
- [four-package-run2.junit.xml](../../publication/native-evidence/four-package-run2.junit.xml)：原生报告，SHA-256 `fa9ec27a5df05be69464d2f96962fd6b33b4bc24fb5adc98ce798d9899183173`。
- [four-package-run2.log](../../publication/native-evidence/four-package-run2.log)：原始 stdout，SHA-256 `b4ee3475b054b631326d1270382a4833a2aab7a48b53dfe21d9145fbe0497cf4`。
- [four-package-original-test.log](../../publication/native-evidence/four-package-original-test.log)：Run1 原始失败和重试记录，SHA-256 `396f2f8b559dacf411599a1223be711157a4d7a912258c692e25c4b22f15385f`。
- [run2-original-scoped-metadata.json.gz](../../publication/native-evidence/run2-original-scoped-metadata.json.gz)：原生 metadata 压缩原件，已核 SHA-256、解压内容、workspace 和包目标。
- [run2-original-scoped-metadata.json.receipt](../../publication/native-evidence/run2-original-scoped-metadata.json.receipt)：metadata 原始命令、退出码和内容哈希；未压缩原件可由上述 gzip 精确恢复。
- [report-only.nextest.toml](../../publication/native-evidence/report-only.nextest.toml)：仅设置原生报告路径的实际配置原件。
- [selected-source-independent-reconstruction.json](selected-source-independent-reconstruction.json)：17 个源码文件的逐字节重建来源与结果。
