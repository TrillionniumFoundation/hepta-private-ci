# B21 collector v3：原 Intel 全上下文失败原件与退出阶段核验

本包记录普通 PR 自动触发的 `42164663819 / 127718214088`，结论为 **FAILURE**。实际 checkout 为 `84cc73453eb926d6f2c5b0372c0287b0ab86ed53`，event merge 为 `285d5727d01e38a76a77441ab038e109dbab787c`，两者树均为 `45858bc96c0edbc366ec77991646b15971129975`。该分支只改变一个诊断 workflow，全部 10,582 个产品叶和模式仍与 main67 的 `3982ba56dc5a3f1da0c1de7ea57992f88125c359` 一致。**它不是 PTY 优化候选 `8075eb367b6e97546af206b27bbf4a3a867497c8` 的结果。**

## 实际取得的原件

官方 artifact `13481118302` 共 78,262,690 B、1,182 个 ZIP 成员，SHA256 为 `656b66f8e430497d65258f6b8cc3ec1312c93d47ef3625b80caba32bbc4cbb8b`。独立下载 HTTP 200；下载后的完整 ZIP SHA256 等于官方 API digest，CRC 全部通过。只保存不含签名 URL 的传输回执。完整 job log 为 1,567,240 B，SHA256 为 `7e3fb7e806b8051eb8c5f803a70416a26837666f06a63bba029a094a76210e02`。

ZIP 内 source archive 为 65,409,614 B，SHA256 `3768639f6442f5f0837332ac31bba393d277dc92f68b1dd684e670f086baa01e`。验证器逐一核对其中全部 10,583 个文件/链接叶的 Git blob、模式和完整 Merkle 树，不执行 archive 中的产品代码。before/after 工作区均干净。实际主机为 macOS 15.7.9、Intel Core i7-8700B；固定 Bazel 9.3.0。

## 不同分母的结果

| 层级 | 原始结果 |
|---|---|
| Bazel target summaries | 438：433 PASSED、1 FLAKY、4 FAILED |
| 原命令末尾概述 | 605 targets 中实际执行 438，434 pass、4 fail、167 skipped；434 包含最终 FLAKY 后通过的 target |
| 实际 shard/retry attempts | 501：495 PASSED、5 FAILED、1 TIMEOUT |
| attempt 日志与 XML | 1,002 份，全部 retained，长度/SHA256 与 manifest 相等；全部 XML 可解析 |
| PTY target Rust cases | 28 通过、3 失败、0 忽略，共 31 个唯一名字 |
| HTTP client Rust cases | 84 通过、1 失败、0 忽略 |
| grpc_notifications Rust cases | 0 通过、4 失败 |
| grpc_tcp Rust cases | 0 通过、4 失败 |
| Core target | 8 shards、10 attempts；首轮 shard 5 失败、shard 4 超时，两者后续由原自动重试通过；summary 仍为 FLAKY |

原 job console 会再次打印 failed-test tails，不能将这些重复文本计成新的失败尝试。Core shard 1 同一 log 内还含一个 1 例通过的 child 段；其 parent 最终结果为 321 例通过，不能相加成 322。所有 Core 原 summary 行和首次失败/超时都保留。

PTY 三个失败为 dropped-output-receiver、preserved-fd Python REPL readiness、close-stdin large-input/EOF。dropped-receiver 在 portable 后端等候 2.13193564 秒后超时；观测到 4,002 次 read、2,050,048 B 已读且已丢弃，状态 waiting_for_read，errno 35，queued_bytes 0，child phase python_started。REPL readiness 在 5.002924503 秒失败，日志已有 Python 3.14.7 banner 和输入 echo，没有 ready token。close-stdin 收集在 5.509082585 秒后 deadline_elapsed，output_bytes 0、child 未退出。**这些是失败时的非原子观察，不证明统一根因、死锁或 CPU/负载因果。** 原 2 秒/5 秒预算、测试代码及断言均未放宽。

HTTP client 失败由测试服务端 read 返回 WouldBlock（errno 35）后 panic 呈现；两组 code-mode-host 都在等 endpoint 约 10 秒时超时。Core 首轮 shard 5 的 308P1F 中，fork-history 测试等待 delivery boundary 超时；shard 4 达到原 900 秒 Bazel 超时。以上均保留原错误，未通过重试结果抹除。

## 进程 38 与本地 BEP 3 是两个阶段

原 `original-bazel-exit-code.txt` 为 **38**，console-copy 为 **0**，collector 为 **1**。本地派生 BEP 的唯一 buildFinished 是 `TESTS_FAILED / 3`。原 console 随后明确报告 Build Event Protocol upload 在四次原有重试后因 `remote.buildbuddy.io` 的 UNAVAILABLE 失败。采集器 `complete=false` 的唯一 error 是 `original_bazel_exit_mismatch`；它要求两个阶段的退出码始终相等。

本包完整保存固定 Bazel 9.3.0 tag 对应 commit `e89755babf3e941bc1e9d8120b1cd48854ab9dfa` 的 ExitCode、BuildEventServiceModule 和 BlazeRuntime 主源及实际完整 GET 回执。ExitCode 将 38 定义为 transient BES upload infrastructure error；BuildEventServiceModule 的 afterCommand 关闭上传通道可抛出异常；BlazeRuntime 可在 cleanup 后用 module exit 替代非基础设施类的原 command result。**据这些主源与本次原 console，可解释为什么测试阶段 3 和最终进程阶段 38 并存。** 这项解释不将任何产品测试失败改成 PASS，也不覆盖已发布的 collector false 或 workflow failure。未修改 collector、原命令、远端服务或重试次数。

派生 BEP 共 7,441 records，保留 501 个 testResult 和全部实际尝试。原 raw BEP 因凭据内容未加入 artifact；保存的是原采集器生成的 credential-sanitized / opaque-payload-omitted 表示及 redaction receipt。三项 opaque payload 省略明确标记；不能称为未清洗原始 BEP。原 privacy gate 扫描 1,180 份文件并额外检查 source tar 与解码后的 compact，判定 safe_for_upload、errors=[]；这里记录该原判定及其有限范围，不宣称无限制检测未知秘密。

## Compact 的证据范围

完整 compact zstd 为 8,895,372 B，SHA256 `7e62ada62895bbf24f330c4a42dae0bcd7bdaf8de539afb12ffaeab463469257`；解码 68,645,745 B、162,228 records。解码使用另包已固定的 Bazel 9.3.0 spawn.proto 和 read-only decoder，其完整原字节随包保留。

四个 FAILED targets 各有原生 TestRunner：darwin-sandbox、cache_hit=false、exit 101、300,000 ms；各自 XML helper 的 input log digest 和 output XML digest 都与本次 retained bytes 对应。产品 TestRunner 自身没有提供可用的 test.log output digest，绑定经它对应的 XML helper 建立。Core 的十个 native attempts 均为 local、cache_hit=false、900,000 ms，exit 分别 8×0、1×101、1×142。

**Core 两次重试存在独立限界：** shard 4 与 5 的第二个 XML helper output record 仍引用首轮失败 XML 的 digest，而新 retained retry XML 的 digest 不同。验证器记录两组原 digest、actual retry digest 和各自 sequence。它没有声称两份重试 XML 已按本次 compact 输出绑定，也没有猜测是谁导致此复用；重试 PASS 的观察来自保留的 BEP、日志和 XML，而非用旧 digest 强行证明。

## 可重放核验与未执行项目

执行 `python3 verify_native.py`，需要 Python 与 zstd，只读校验官方 ZIP、source archive、真实 API/publication、BEP/manifest、日志、XML、compact 和固定 primary。它不运行 Rust、产品测试、OS 机制实验、CI 或远端写操作。根执行 exit 0，stderr 0，stdout 16,908 B，SHA256 `4d6c51be532d1042f12fd997591b7855807dcc05e454950c5b3375a8f87a3317`。

`development-history/` 保留三轮离线验证器假设修正：误将 B21 HEAD checkout 当作 B23 merge checkout、未区分 Core child summary、未接受 Rust 的 `- should panic` 输出注解。修正只影响离线解析，所有原 ZIP/log/source 不变。临时下载 URL 从未进入本包；V8 URL 构造器和超长 shell 参数的两次编排问题也在 notes 说明。

本包只增加原失败的可复核性，**B21 与 B15 仍 OPEN**。原 Intel 实际 drain 失败的充分因果解释和修复源在原上下文的验收仍待完成；独立候选的绿色运行不能倒填本次原失败。
