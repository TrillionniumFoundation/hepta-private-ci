# 修复 Clippy 回归后的共同候选 S

在精确 S 上重新实际运行的 **74 项 Python 控制、5 项 AWS Auth 测试和 33 项原生 UI 包测试全部通过，零跳过**。Bazel 锁一致检查与完整 tracked 源码归档核验通过。独立 Rust 1.95 Clippy 原失败命令也实际通过。**cargo-deny 仍只因 RUSTSEC-2026-0451 失败；整体门禁未通过。**

## 源码和证据身份

| 身份 | Commit | Tree |
| --- | --- | --- |
| 原冻结 C | b839558b26c2e5b667055ca4af4ad749ae41c043 | e411d25b47c166f35783a27054adb6a3f6682594 |
| 原证据 E | 6c63d1aab2a4914c3559b368b1ade5a4748e8df7 | 0290f23d80cbbca7a7fd9be546dbb305a05c70f9 |
| 前一共同源码 R | cfe941b4762a773679a552068d1560ae17a3f226 | e6fc9a1cb7c2441c1811d08356f7e31b2e886177 |
| 前一证据 F | fbccef047dfdd435808796dfc5d2d4223eb645c8 | 7d2a1cc8c8a45f9f07c7cc4e5c4179941bb9443d |
| 本次实际受测 S | 693a013b254d07779f6f2b2a78d0ee31481f4ea9 | f06389aa4f5caf0af5fec419da6473e198796b24 |

S 的 parent 是 R。R..S 仅 `room_ime_commit_tests.rs` 一行 `text_input(&mut cx, ...)` 改为 `text_input(&cx, ...)`，1 行新增/1 行删除。原生产接线、测试断言和锁文件不变；源码冻结前后格式检查通过。本证据分支 G 从 S 建立，只新增 observations 文件及原始证据包的精确 SHA256 allowance，运行源码与 S 相同。G 自身 head/tree 与发布回读由独立交付收据记录，不预填未来提交身份。

## R 的托管失败历史与 S 的新验证

R 的 hosted native-presentation jobs 128855152428/128855152530 使用 Rust 1.95.0，实际 source-head 是 R，base-merge `29e4c3e669089e3efa50a1948496e452c6802b59` 的 tree 也为 R tree。原 before/after 执行回执和完整日志定位到上述新增测试行的 `clippy::unnecessary_mut_passed`；`-D warnings` 令该命令退出 101。R 上已通过的测试不计入下面 S 的分母。

另三个 R 相关已结束 job：cargo-deny 128855244522、Bazel GNU 128855244828/musl 128855244840，日志实际 checkout 是 `4bc603a8e38886b72c3ab4a3367cc9cf9968d234`（parents C/R、tree 为 R tree）。deny 仅 0451；两 Bazel lane 各 408 passed/6 failed/164 skipped。五个此前 C 相关失败症状复现，另 `hepta-infer-worker-host` 的终局 reconciliation 测试出现 WriterUnavailable（该包 49 passed/1 failed）；此新增观察的因果尚未证明。不能把这些失败统称旧问题，也不能说本次一行 Clippy 修复已解决它们。历史报告和原件 pins 放在 raw 包的 `prior-R-ci/`；未重跑或改写这些 CI 结果。

S 的本地共同验证与 Rust 1.95 Clippy 分别记录；没有用本地检查代替新的托管 CI 回读。

## S 实际验证窗口

| 门禁 | 实际结果 | Wall 秒 |
| --- | --- | ---: |
| common-python-controls | 74/74，0 skipped | 14.308529 |
| aws-auth-tests | 5/5，0 skipped | 3.521692 |
| native-ui-package | 33/33，0 skipped | 2.828860 |
| bazel-lock-error-check | 通过 | 5.879310 |
| cargo-deny | 失败：0451 | 2.820261 |
| complete-archive-integrity | 通过 | 1.465412 |
| 独立 Rust 1.95 Clippy 原命令 | exit 0 | 34.743610 |

`VALIDATION.json` 保存共同窗口的所有 argv/cwd/env、每一步前后源码身份、stdout/stderr 长度及 SHA、退出值与成本。三个测试组均在 S 上从头执行；112 只是这三组工程测试之和，不是科学样本数或项目总覆盖率。Bazel 这里只执行 `mod deps --lockfile_mode=error`，没有执行上述 578 个 hosted targets。

共同窗口 Python 3.12.3，torch 2.9.1+cpu、numpy 1.26.4、Pillow 12.0.0；四个线程变量均为 1，六个模块与原 C profile 的精确字节另行保留。Rust 共同测试使用 1.96.0，通过 `just test` 执行。独立 Clippy 使用 1.95.0，命令为 `cargo clippy --locked --manifest-path apps/hepta-control-ui/rust/Cargo.toml -p hepta-robrix-ui --all-targets --features ui,native-host,native-presentation -- -D warnings`。各环境真实二进制 pins、目标目录与预算见各自 profile/receipt；不能说两窗口环境完全相同。

### 字体与实际 SDK 字节

两个窗口各自记录：安装前源码严格 clean；测试期间只有 manifest 指定的两份 Noto 字体为受控 untracked 文件；按各自 bytes/SHA 核对清理后恢复 clean。manifest SHA `fb9e49a7f14b742ac7e390ceee9be115ad6e04a5f852eec67fb0a126870070a3`；URL、大小、SHA 和保留缓存路径均在 profile。字体不是 tracked source archive 的一部分，不宣称运行期间 status 始终为空。

共同 112 窗口实际解析 Makepad checkout `/home/qian-qi/.cargo/git/checkouts/makepad-69d78fae78fc8901/337566c`，HEAD `337566c8b25d47f7e4fff6a202157b65bf183330`，tree `c6e18be7754f9634492ec5251bac3e8b4f7e09b7`。前后 status 都保留 `?? .cargo-ok`。29 个 CSV/PS1/CMD/BAT 按 SDK attributes 从 Git LF 字节物化为 CRLF，精确 Git/实际 SHA、bytes、变换与 attributes 在 `runtime-inputs/SDK_CHECKOUT_NORMALIZATION.json`。全部 6008 个 Rust 文件均原始 Git blob 相等，其他受控 SDK 文件与冻结物理 pins 相等；UI 前后完整 SDK 输入身份相等。未改 SDK/Git 配置，也未删除 Cargo marker。

独立 Clippy 的依赖核验范围较窄：SDK HEAD/tree/status/tracked diff 加两个物理 SDK 文件、8 个源码/锁/helper 文件，均前后相同。不能把共同 112 窗口的全量 SDK 检查追溯归给 Clippy。原 WASM IME patch 有独立 SHA，但未应用于原生 SDK；浏览器 JS→WASM、Firefox、Playwright 和设备 renderer 未由本报告证明。

## 准备、执行与成本

本次先完成 S 独立 worktree、格式、Python/字体/SDK/原 Clippy 回执和 `cargo metadata --locked --offline` 的非测试 preflight，再冻结新 profile 并运行共同测试。旧 R 的失败尝试与局部成功保留在 R/F 历史，不混入 S 成绩或成本。

**启动记录缺口保留未决。** 已确认的共同 job `1a1bd027b6b-138b0-572` 的 idempotency key 是 `cell-clippy-08b6-S-common-validation-002`，输出目录仍为 `clippy-common-validation-001`。001 这个 key 的原客户端请求/拒绝文本在上下文压缩后未恢复，是否发起、是否在 admission 前拒绝均不能确认；不能写成肯定未调用，也不能记为 0 成本。完整 `h_process_list(host=rog)` retained inventory 中，指定区间仅有 preflight 56c 和共同 572 两个身份，未发现另一个已登记 job；该 API 不暴露 key 字段，也不是未登记请求未发生的证明。完整主机 inventory 原件仅留 native 私有路径与 SHA/bytes，不进入最终 Git/交付包。`STARTUP_RECONCILIATION.json` 与 raw 包 `startup-evidence/retained-jobs-rog-interval.json` 只收入这两行、过滤条件、请求参数、完整性/总数和私有原件 identity。

112 项只归属于已有权威 succeeded/exit 0 的 job 572，独立 Clippy 仍归属于其原 job。以下费用只覆盖已观测执行窗口；完整客户端启动历史和端到端费用尚未建立。本次未因证据缺口重跑测试。

前份未发布证据 G2 commit `ed6bd2eaa281c0ee9d718e5a03f4c92c3d5ec061`（tree `18acea79275b7bc47ed74f46c28a27f9404f0ce2`）保留在 native 分支 `engineering/cell-integrated-20261108-08b6-clippy-evidence-second-unpublished`，其原 delivery、包 SHA 和操作回执也保留。G2 已明确启动记录缺口，但本地原始包误含完整主机 inventory，因此被仅包含最小区间摘录的本份 G3 替代。G3 直接以 S 为 parent，最终 R..G3 bundle 的可达对象不含 G1/G2 的旧证据包。首份未发布 G1 `a35cbe7a73ffbbb3ec76ed0d9f8c6a9deca4ac81` 则因遗漏启动记录缺口而被替代，其原 identity/pins 也在历史交付收据中。两个旧版本均仅保留本地未发布历史，未重写原件；C/E/R/F/S 与实际测试原件均不变，本版亦不声称已发布。

| 独立窗口 | Wall 秒 | CPU 范围 |
| --- | ---: | --- |
| S 非测试准备 | 3.735903 | 进程及后代 3.078226 秒 |
| S 共同验证，含失败 deny | 43.787670 | 进程及后代 45.382230 秒 |
| S Rust 1.95 Clippy 验证 | 35.105182 | 已记录子进程 59.545041 秒；controller CPU 未测 |

三个不重叠活跃窗口 wall 合计 82.628756 秒；Clippy 命令 34.743610 秒包含在其 35.105182 秒窗口中，各子步骤不能再累加。复用了已释放 Cargo targets 与缓存，不声称冷构建。源码修改/冻结、窗口外依赖准备、CI 诊断、封存、传输和发布成本不在此表，亦无新增训练或确认集实验。

## 完整源码归档与限制

`git archive --format=tar --prefix=source/ 693a013b254d07779f6f2b2a78d0ee31481f4ea9` 的完整原件保留在 `/home/qian-qi/work/cell-integration-20261108-08b6/clippy-common-validation-001/source.tar`，162334720 bytes，SHA256 `fb94f5f064aec383d5ac8e839c8e4a51995165651491b7f83782bdbd50a9193a`。原 `hepta_source_archive.py` 对 11,387 tracked 文件的完整集合、原始字节、模式和 symlink 实际核验。完整 inventory 在 raw 包 `clippy-common-validation-001/archive-integrity.json`，SHA `49e57f89f61c7e54d1e2924022990f3bd9b1f2759fa5b2ee7682cc960754551f`。归档是 S 的 Git 字节；运行字体和 SDK 的物理字节身份另行绑定。162 MB 源码 tar 未重复入 Git 证据包。

archive 核验只有 integrity 意义，不认证测试执行或发布。`joint_learning_configuration` 仍为 null，scientific/production qualification 均 false，overall gate false；vodozemac 0451、其余托管失败与跨平台限制仍需处理。没有运行新的固定图学习采用实验，没有重跑 PRED 确认，原 HOLD 不变。

复现入口是 raw 包保留的原 `prepare_successor_s.py`、`validate_successor_s.py` 和独立 `clippy-S-native-evidence.tar.gz` 内的 worker；固定路径、原始命令及输入 pins 均需按各自记录核对，不得把改路径或环境后的结果称为同一原始执行。`CONNECTOR_JOB_OBSERVATIONS.json` 保存实际 h 权威终态；控制进程 succeeded 不覆盖内部 cargo-deny failure。
