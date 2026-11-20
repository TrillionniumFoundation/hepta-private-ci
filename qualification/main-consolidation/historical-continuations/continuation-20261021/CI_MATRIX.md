# CI 与本地验证矩阵

**最新发布前增量为01:54:37 UTC**：#2968仍未获得两个required汇总成功；
#2969 Architecture required成功，cargo-deny及三个Windows Bazel分片失败；
OS两条head各6成功、内核测试仍运行。完整计数和来源见
[PUBLICATION_DELTA.md](PUBLICATION_DELTA.md)。以下保留01:35:51及本地执行证据的原时间范围。

远端记录取于 **2026-10-21 01:35:51 UTC**，非原子快照；逐项 ID、app、SHA、
started/completed 时间在 [ci-live-final.json](ci-live-final.json)。
pending/queued/in_progress/skipped/metadata success 均不等于完整 gate success。

## 当前精确 source 的远端状态

| source / 工作流 | run / job | 观察状态 | 结论 |
| --- | --- | --- | --- |
| #2968 `b11459f4...` blocking-ci | run 39528171977 | pending | 未通过，不能合并 |
| 同 source Architecture | run 39528172005 | pending | 新 current-base 资格尚未完成 |
| 同 source UI | run 39528171904 | pending | 原六个产品 case 与 native completion 仍必需 |
| 同 source V8 | run 39528171897 | queued | 不能以旧 metadata 成功替代 build |
| 同 source Windows private-state | run 39528171964 | queued | 安全限定资格，不能替代整个 Windows matrix |
| 同 source Bazel lock proposal | run 39528171953 | queued | 本地 stable lock 成功不等于该 hosted 作业完成 |
| 同 source keyring proposal | run 39528171902 | queued | 本轮未将 proposal 产物当作已采纳 backend migration |
| 同 source schema refresh | run 39528172010 | skipped | 明确保留 skipped，未计为通过 |
| #2969 `ca276897...` blocking-ci | run 39524743211 | in_progress；已有 deny failure | 仍阻塞 |
| 同 source cargo-deny | job 118977201311 | completed/failure | 未取得该 source 的 dependency gate |
| 同 source Architecture | run 39524742971 | queued；required job 118985386163 queued | 完整 required 未完成 |
| 同 source Reader/harness | run 39524743076；Reader job 118976636455 | success | 125 contract tests +64 实际 Reader calls，限定此资格范围 |
| 同 source Stem/Reader bridge | run 39524742899 | success | 契约成功，不是新训练/生产认证 |
| 同 source V8 | run 39524742890 | success 但 build jobs skipped | 仅 metadata 范围，不是完整 V8 平台通过 |
| OS #224 `49e5582d...` | ktest run 39527232732 / job 118984639491 | 六项 checks queued | 旧 head a8d2... 的结果不转移 |
| OS #225 `9476f50e...` | ktest run 39527383034 / job 118985116581 | 六项 checks queued | 旧 head 84e2... 的结果不转移 |

#2968 在快照时 5 个已出现 check-runs 中 4 queued、1 skipped，两个正式 required
context 尚未出现。#2969 44 个 checks 为 success 17、failure 1、in_progress 15、
queued 1、skipped 10。这里只是 check 对象计数；job/matrix/workflow 的分母不同，
不据这些小计推算“平台通过率”。

## 本轮真实本地执行

| 测试与输入 | 实际结果 | 资格边界 |
| --- | --- | --- |
| Git executor/deadline/output，最终 Python patch | 54 passed，0 skip | Linux 实际 Git/process 回归；没有把记录型命令 stub 当作 Rust 编译 |
| f740 Memory --lib | 271 passed、1 failed、7 skipped | 精确记录旧迁移期望失败，未覆盖为成功 |
| 未改 0cb 的 migration 单项负控 | 1 failed，exit 100 | 确认真实回归可复现，filtered 项不当作执行 |
| 最终 combined tree +两锁+fixture：Memory --lib | 272 passed、0 failed、7 ignored | 完整该库默认测试；不含被 ignore 的资格/stress/crash probes |
| 同候选 cargo-bin locked package | 2 passed、0 skipped | 实际 workspace 版本；此前 isolated harness 的范围另行保留 |
| 同候选 Memory/cargo-bin strict Clippy | 均 exit 0 | 显式 deny correctness/await-holding/expect/unwrap；没有声称 blanket -D warnings 通过 |
| 同候选收尾 just fmt / diff check | 均 exit 0，无字节改变 | fmt 后没有仅为格式重复测试 |
| 三次 Cargo precise update | exit 0 | 3 TLS 升级 +9 Windows edges 全部记录 |
| just bazel-lock-update ×2，原 just bazel-lock-check | 均 exit 0，第二次生成字节稳定 | 真实 Bazel 9.3.0；不等于全 Bazel test/clippy/release |
| cargo-deny 0.19.0 --locked --all-features | 7 errors →4 errors | security gate 仍失败；没有追加 advisory ignore |
| Reader qualification Python 全集 | 125 passed、0 skipped | ca276 对应文件；16 新 test methods +独立 adversarial/兼容检查 |
| 历史 Memory archive 当前 verifier | 272 文件通过 | 只读重验，0 本地模型调用 |

native 最终运行对象是 `6b074e52621d77338112f02119beb0cb1a6f869f` 的 combined tree
加三文件 diff `99ba4b1d81447b477e44bf414f8da398739746f74b591c3e30a8b31385a232a1`。
该源码/锁与已推送 b114 一致，后者另有 THIRD_WAVE.md；原 receipt 保留原测试身份。
本地 Rust/Clippy 1.95.0、Linux x86_64、two jobs。它没有提供 native Windows/macOS
或 whole-workspace 的资格。

## 旧失败和剩余平台责任

0cb 架构 base-merge job 118980327865 在测试前失败；event base603 与随后确认的
实际 merge parent98b 不同。已通过保留 owner 的真实合并处理基线变化，新门禁尚待完成。
旧 #2944 Windows 日志的缺 host runfiles、fixture handle 问题已有父 owner 更新；
其他 Git wrapper readiness、RPC/metrics、sandbox helper、guardian 等失败需分别
在新 Windows head 复核，不能以修改源码推定全部修复。历史 macOS/原生 ENOSPC、
V8 上游 HTTP 503 原始失败也保留，详见 [ci/README.md](ci/README.md)。

main 的原始必需上下文仍为 `CI required` 与 `Architecture required`（app15368）。
没有取消平台矩阵、放宽 assertion、改 skip 规则、关闭保护或人工伪造成功。
