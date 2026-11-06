# H2 fd-exec 采集与原门禁组合独立窄审

审查对象为 H2 `620cb63ae9b58904483005bcb2c4e1507df99539` / tree `f2cebe6d99deca596c170922b8e60d66648d7393` 的外部执行配置。结论：在以下明确范围内，没有发现新的具体执行阻断或将失败升级为 PASS 的路径。本审查没有新增桌面动作、Cargo、采样或产品测试；最终资格必须来自该冻结版本的完整原 sequence、实际终态和最后 source/configuration guards。

## 冻结对象

- Runner `nextest_fd_runner.py`：`903c622365c9cf863f1ae4b5eca2d4a0501c9f86862538c48f94f126a82ba62b`。
- Gate verifier `fd_gate_evidence.py`：`b582bbc5759f5dbadff6416f7aa804f67e6136d18553c7b6486bd8a7786435c6`。
- Coordinator `run_h2_native_pipeline.py`：`700c8a3df4997f0d3348bbab6df4ad8b23865cb935e231a51f5171cd34e6a350`。
- Plan `h2-native-plan.json`：`5f79297d78b0b1b2aa13022c4eed26bee8cff788a2eafd4086e9f3261c7e0288`。其中旧 workflow blob 元数据已纠正为实际 `487bf796005439547ff1ac0366648a0f2daf236c`；原命令未因这项修正变化。
- Launch bundle：`d73dc5d0095dcec709494a662964a2997a1b7b9f0a290a18e294c5f278bfb390`；本审查独立逐 hash 核对其 launch plan 所列的 9 个文件，已保存这些确切文件快照。

`review.json` 给出每文件字节数/hash、每个原 workflow step 的 command/minimum/deadline/env 对账以及实际 utility 证据。官方 cargo-nextest 0.9.103 接口审查另见 `../nextest103-runner-review/review.md` 与其 source inventory。

## 每个测试的链条

Runner 从 Cargo/nextest 提供的绝对测试 ELF 路径打开 `O_RDONLY|O_NOFOLLOW` descriptor，要求 canonical target 目录内且文件名匹配当前 gate 的 crate/hash。run phase 必须携带精确 `--exact NAME`，且只命中一个登记的选择；list phase 直接透传，没有测试资格。

run phase 从该 descriptor 读取并留存 ELF，检查开头 ELF 标识、regular file、读前后 inode/device/size/mtime/ctime，复核自身 PID/start ticks、coordinator ancestry 和 pathname identity，写入同步落盘的 pre-exec record，再对同一 descriptor 执行 `os.execve`。没有 fork、cwd 或进程组变更。一次运行的记录不依赖 polling 能否恰好观察到短测试。

Verifier 要求真实 libtest case 与 record 的 exact-name Counter 完全相等且每项恰好一次，PID/start-ticks 不重复，nextest 声明恰好一个 test binary。它拒绝 `*.exec-error.json`、残留 `*.pending`、空记录、重复或缺少记录、不同 source/config/runner hash、错误 argv/name、多个实际 ELF hash、留存字节大小/hash 不匹配。每 gate 在下一次构建前独立重哈希该 gate 的留存 ELF。

Pre-exec record 不单独产生 PASS。Coordinator 先要求原 wrapper receipt、wrapper exit、command exit 都成功，再要求精确 selected names 全部真实 `ok`，最后要求 fd bijection 和唯一实际 image。FAILED、selected ignored、exec 异常、缺 raw 或任一捕获错误都不能被 record 掩盖。旧 polling 仅作旁证：漏掉短 case 可以由本次该 case 自己的 fd-exec record 加真实结果闭合；若 polling 实际捕获了进程，则 PID/start/hash 必须对应同一 fd record。没有用别的 case 或 H1 的 hash 补记漏捕。

## 原命令、数量与预算

独立解析了当前 formatted workflow 的每个原 step，对账所有 command argv、minimum、timeout 和 step env，均与冻结 plan 一致。实际 71 个互不重复的 exact names 与持久 CI guard 的集合相同，包括新增 settled-absence 两例。原顺序保留；fix 仍 1200 秒，fmt 仍 300 秒，额外兼容/provider/FinalUse/full-library gates 独立保留原 wrapper 限额。

完整 evidence library 的历史 wrapper `minimum_tests` 是 **22**，H1-extra 与 H2-extra 内容完全一致，没有改这个原值。它不是本次完整库验收条件：coordinator 另要求固定 **161 个 exact names 全部 ok**、nextest 声明 **161 executed / 1 skipped**、全部 161 个 case 与 fd record 一一对应，并从已绑定同一 ELF 读回唯一既有 ignored 名 `authbus_outbox_tests::crash_delivery_child`。必须准确区分旧 wrapper floor 与更强的完整库硬门禁，不能把 22 当完整库执行数。

本轮保留默认每测试 30 秒 × 2 的 60 秒终止设置、`--retries 0`、原 test threads、全 coordinator 5400 秒外层上限。按官方固定版本执行器，计时围绕 runner 子进程，fd-exec 不重置 timer；读取/留存/fsync/hash 的额外开销在原预算内。Discovery 自身不获得 per-test credit，仍受所在 gate 和外层总预算约束。最终 source/configuration guards 也在总预算内；只有步骤级 `passed` 而没有最终干净终态不能给整阶段信用。

## 已有 utility 证据的真实范围

读取并逐 hash 核对了 implementation owner 已执行的桌面 utility：3 tests / 0 failures、原日志 `88ee443995fac670b02034677d22b95af16453ad846bdbb30c65c71c54fea080`，测试内部报告 2.183 秒。它实际验证了 8 个短 ELF 进程的同 PID/hash/inode 记录、discovery 透传与不计数、未选中名字拒绝、模拟 FD identity 变化及真实失去执行权限后的 exec-error。

这些 utility 是直接调用 Python runner，并没有实际调用 cargo-nextest，不给予 Rust 产品信用。nextest 会采用该接口的依据来自官方 0.9.103 源码；实际 H2 集成是否采用、全部 case 是否通过，将由本轮严格原 gates 决定。本审查没有要求或执行额外可选测试。

## 保留边界

这是明确新增并冻结的 H2 execution configuration，不是与 H1 配置字节相同，也不补认 H1 的三次 polling 漏捕。它只绑定 exact test ELF；ignored/Python 字节观察另有限定范围，不等同完整 dynamic runtime closure、所有孙进程完整闭包或 hosted matrix。

读 descriptor 不自动阻止另一个主体写同 inode；本方案仍依赖独立 target、无并发构建/修改、读前后 identity 与最终 retained hash 的既定工作边界。源码和 external runner/coordinator 文件都被前后 hash 检查；本报告没有声称能对恶意并发 writer 提供更强的内核封存性质。
