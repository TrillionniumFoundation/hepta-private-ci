# 旧 holdout 作业失败与当前 ac18 的适用性窄审

**结论：旧 holdout PR 的这次 scoped Cargo 作业没有暴露文件锁 guard/test 失败。六个 fenced_holdout_file 用例全部通过；作业失败来自三个 arg0 测试缺少正常 main fixture 二进制，以及一个独立 Supervisor 超时。arg0 的 Cargo 构建前提在当前 ac18 源中仍未补齐，已有 Clippy donor 不修复这个缺口。Supervisor 超时只能定位到两个阶段标记之间，尚不能给出内部根因。没有把旧结果自动转授成 ac18 的实际失败或通过，也没有关闭 blocker。**

本次只读分析已经取得的完整日志、官方 artifact 和固定源码。未查询新的 CI 状态，未发起 native、dispatch、重试或取消，未修改 ref、PR 或产品源。下面的补丁方向目前是可审实现计划，不是已生成/执行的 postimage。

## 1. 原始身份与不同分母

原作业为 run `42176273058` / job `127755476318`，名称 Hepta scoped native checks，唯一失败步骤为原 “Test affected owners and reverse consumers, not a hand-written package list”。实际 source-head checkout 为 `4a1410f332e4a34564feafbc4dcb2e808c7f6c5f` / tree `605720504e547296dca1c78914fee5ed6d29844d`，唯一父为67。原 `impact-test.json` 的 before/after 完全相同，dirty=false，命令 exit100；执行器自身 timed_out=false、output_limit_exceeded=false。[E1]

官方 artifact `13486100626` 为 `hepta-cargo-impact-42176273058-1`，完整 ZIP **379,045 B**，SHA256 `e7d981ea110d109c40b5e290ba23e6f5c9262c01debacd5b728d94c5d4a45813`。官方 run artifact 元数据的 size、digest、run/source 与本地 ZIP 相等，三成员 CRC 和展开字节全部一致：

| 成员 | 完整字节数 | SHA256 |
|---|---:|---|
| cargo-impact.json | 3,577 | 66d0e8fe0fbe418f98486bb20321783fa07b8f51bdef42f2ad7b6cbcc0743497 |
| impact-test.json | 1,721 | f2ebb3212f23ad257584cddcf43342940ffa817cff78319a9d8d34327f36ef20 |
| impact-test.json.342bb7e280f9412a9889fb6dc7cfb580.log | 2,284,485 | 11c564a3fe25e105ad4ac775eed9b6b189278615d00eb2e67c0c9ff974c9c0af |

完整原 job console **4,329,523 B** 与工具返回的 UTF-8 全文逐字节相等；上传摘要中的 artifact digest 也相同。它与 artifact 的内部命令日志是不同原件，不混算字节数。[E1]

原 plan 有 **20 个 changed_packages、127 个 selected packages**，full_workspace=false。原 nextest 终态为 **17,800 tests run = 17,796 passed + 3 failed + 1 timed out**，另有49 skipped。2 flaky 已含在17,796 passed中；不能再加一次。17796P是这个完整127包 suite的结果，不是 holdout 单包的通过数。[E1]

## 2. 六个 holdout PASS 能说明什么

原 log 的12610–12617行中，六个 `fenced_holdout_file::tests` 均为PASS：原来的子进程恢复、回放/备份回滚拒绝、长分叉历史拒绝，以及新增的 duplicate-file 仍开着时 drop / failed_create / failed_recover 解锁三个用例。[E1]

原4a树已由完整67树只替换这两个文件独立重算得到605720；10,580其它叶不变。当前整合ac18/treec3e9中的对应两文件，就是之前原fmt作业给出的三块换行后像，完整非空白字节与4a相同。[S1]

因此，这条记录**没有提供“holdout guard 或其新增测试失败”的依据**，也不支持为修复该作业而回滚 guard。六个PASS仅是该 Linux/4a 执行的有限证据；不能转写成原Mac失败已完成单因果证明、当前ac18重跑已通过或整个作业通过。[E1][S1]

## 3. arg0：真实失败发生在 child spawn 之前

三个最终失败用例为：

- `actual_apply_patch_helper_precedes_preflight_without_normal_startup`
- `preflight_precedes_aliases_and_runtime_and_default_entry_keeps_its_lifetime`
- `refused_preflight_has_no_alias_dotenv_or_runtime_side_effects`

每个首attempt与retry都在0.006–0.008秒内失败。六份原错误相同：找不到 `test_arg0_preflight`，`CARGO_BIN_EXE_test_arg0_preflight` 不可用，且 Cargo sibling 路径 `codex-rs/target/debug/test_arg0_preflight` 不存在。[E1]

固定源码表明，`ChildFixture::run` 首先执行：

```rust
Command::new(codex_utils_cargo_bin::cargo_bin("test_arg0_preflight")?)
```

原错误来自共享 resolver 的 NotFound/Cargo sibling 分支。因此失败发生在构造真实子进程、运行 normal Rust main 和用例后续断言之前。它既不是 preflight 产品逻辑的断言反例，也不是那个 OwnedChild 的旧 `expect` 触发。[S2]

这里需要区分两种构建入口：

| 固定来源 | 实际合同 |
|---|---|
| arg0/Cargo.toml，a28f6a0bbd75e744e13ad9af22713192f6e6802d | 已声明正常bin `test_arg0_preflight`，`test=false`、`bench=false`；原包没有tests/ integration target。 |
| arg0/BUILD.bazel，a61d1808ccabb55308f4771fc0c326903fc8cc4f | 已通过 `unit_test_extra_binaries` 声明这个helper给Bazel测试。 |
| utils/cargo-bin/src/lib.rs，c180a3e2c01b555ba96c9a87f8354ef9d0c38d3e | 先检查声明的环境变量，再作有界Cargo sibling解析；不自行编译，也不改走任意路径。 |
| blocking-ci → hepta_ci_dependencies → just test → run-nextest.py | 选择完整受影响包后运行原nextest；没有该normal-main helper的显式前置构建步骤。 |

固定Cargo1.95官方test文档区分普通bin与libtest harness，并说明普通bin自动构建与integration tests有关、test=false改变默认测试选择；build文档描述普通目标编译。这与原manifest、执行链和已观察的缺件相一致。这里没有声称已实际执行新的Cargo命令。[P1]

当前ac18源已经包含arg0 Clippy donor，但它只把原三个expect改为Result路径。独立比较证明：旧/current `ChildFixture::run` 从函数入口到 `command.spawn()` 的完整前缀逐字节相同。Cargo.toml、BUILD、resolver、run-nextest、依赖执行器、justfile、blocking workflow在67、4a、ac18中也是相同blob。[S1][S2]

**所以，同一Cargo入口的fixture构建缺口仍适用于当前源的静态合同。** 这不等于ac18正在运行的CI一定选择旧hepta-scoped路线或一定重现：ac18还包含Cargo双锁与其它后继修改，实际scope、平台和执行条件必须使用其自身原件，不能由旧作业代替。

## 4. 可实施的最小修复方向

应补齐原fixture的正常二进制构建前提，保留原三个测试、resolver与真实normal Rust main。针对这次有直接证据的scoped入口，最小方案是在 `hepta_ci_dependencies.py` 既有plan已经选中codex-arg0且执行action=test时，在原suite前运行：

```text
cargo build --locked -p codex-arg0 --bin test_arg0_preflight
```

原 `just test --locked ...` 的包列表、顺序、环境与命令继续由原plan产生，不添加 `--all-targets`，不把helper变成test harness，不把测试搬家、skip或改断言。该构建命令只生成原声明normal bin，不执行它；真正执行仍由原测试负责。

实施时必须保留以下不变量：

1. 原selected packages/full_workspace逻辑完整保留；没有选中arg0时不插入该构建，不能改小测试范围。
2. 构建使用同一workspace、锁、Rust工具链与原Cargo构建环境；不手工复制预编译helper或放宽resolver路径。
3. 构建失败就停止下游suite并透传真实退出码。普通scoped路径已有外层 `hepta_ci_exec`，构建与suite必须都留在它的完整日志/源码前后检查范围内。
4. 对现有 `--record-output` 路径，需要明确保存构建步骤的非覆盖回执/失败状态，不能只记录后面的nextest，也不能因构建失败而留下误绿的suite结果。
5. 原nextest重试、并发、60秒watchdog、所有断言与选择均保持。必要离线控制应验证选中/未选中、构建失败阻断、suite失败透传和原命令完整性；不把fake当真实Cargo/native资格。
6. 真实普通PR CI里实际生成bin并让原三测试执行，才可接受修复效果。本次尚未形成或发布该postimage，没有宣称修复完成。

这个切口比修改arg0的行为或放宽路径解析更贴合真实失败，但当前仅为依据原件形成的计划。通用 `just test` 各种用户参数/feature/profile的fixture支持是另一实现范围，不能在这里未经审查地假定一个硬编码prebuild覆盖所有调用方式。

## 5. Supervisor 超时单列

`five_real_pairs_adopt_all_ten_children_and_isolate_one_matrix_crash` 两次都达到 `ten_children_ready`：TRY1为25.731405657秒，TRY2为23.104750134秒；随后没有 `ten_children_adopted`，在60.005/60.008秒被原nextest watchdog终止。之前的warm_pair_complete分别为4.762873829/3.951018256秒。[E1]

固定测试 `paired_process_product.rs` blob `c03bdba974ea48281cd839b9161eb0ccdc38b892` 在两个标记之间收集已记录PID、drop旧Supervisor，然后调用 `Supervisor::recover`。本次原件没有细分该区间的内部阻塞位置；不能只凭阶段消息把它归为holdout、arg0缺bin或已证主机负载问题。该测试与nextest配置在当前树中相同，但其下一次运行结果仍需当前原件。[S1][S3]

本审查没有改变60秒、删减五对十子进程、放宽adoption/隔离断言或新增诊断运行。

## 6. 独立校验与后续材料

`verify_applicability.py <本审查目录> <old-donor-terminal目录>` 只读核官方artifact与作业元数据、完整console/MCP相等、ZIP三成员与原report、全部首/重试及终态分母，再重算旧/current完整树、源叶关系和原执行命令。它只调用Python标准库和固定函数AST，不运行Cargo、Bazel、Rust或产品程序。最终第二次执行exit0/空stderr，完整stdout保留；第一次尚未补官方元数据/console绑定的成功结果也保留。

### 来源

- [E1] `integration-ci-review/old-donor-terminal-20261106T0840/` 中官方run artifact集合、旧blocking jobs原返回、完整job log及MCP、完整ZIP与展开三成员。完整原件由收件owner单独封包；本审查不冒称其尚未给出的registry已完成。
- [S1] `authority/base67-full-tree.json`、`authority/ac18-full-tree.json`、旧/新实际commit/merge原件、`authority/holdout-source-map.json`。当前固定head为ac18b623c7a6cb953b4660979e9b620fe7176bb2，merge c9baaf38b95da145fb4f9d371b8d134169d313cc，parents[63652be658ebed8d3052eb789b951793384fd5e4,ac18]。
- [S2] `source/`、`old-source/`、`current-source/` 与完整Git blob GET原返回。依赖执行器2403d7a16f14e919952db597dad3ffdc0825cc31，nextest入口1ed63abe84267b320cbfb0123a70aac5507f4595，justfile a215a76cf407ace9715bca39c20497014e7dd4dc。
- [S3] 同目录固定paired_process_product测试和nextest配置868f75986ea9719e116b8fa8a0aa53bd269bc830；同事仅对该阶段范围作了独立静读，未作新原生归因。
- [P1] [Cargo rust-1.95.0 build原文](https://github.com/rust-lang/cargo/blob/rust-1.95.0/src/doc/man/cargo-build.md)、[test原文](https://github.com/rust-lang/cargo/blob/rust-1.95.0/src/doc/man/cargo-test.md)，完整原返回在cargo195-build-test.github.original.json。第一次网页工具DisabledError原件另保留，没有把失败返回当文档内容。

