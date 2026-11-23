# 2026-11-23 12:23 UTC — #7032 与 main 的 cookie 双依赖图原生安全读回

本记录是**新增的只读回验材料**，不修改原始研究、原失败、Cargo-deny 守卫、公开 V1、测试时间/名单或产品授权。所有结论绑定具体 Git 提交和原生 Actions 作业。已完成作业没有再次派发。

## 精确科学源上的可逆候选：独立三门通过，但尚未采纳

- 原科学 head：`610f91087b598656f7f3913e600c705b95bf071f`（#7032，原 blocking-ci [45162302912](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/45162302912) 的 cargo-deny [137652317812](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/45162302912/job/137652317812) **失败**，`cookie 0.18.2` / `RUSTSEC-2026-0594`）。
- 修复分支 `fix/hcsn-7032-cookie-rustsec-20261123` 当前固定 commit [`b1af67a38f8cf9cee700cc067da1e6001ce220a8`](https://github.com/TrillionniumFoundation/hepta-private-ci/commit/b1af67a38f8cf9cee700cc067da1e6001ce220a8)，从科学 head **只前进两项提交**，逐文件 Git compare 仅修改 `codex-rs/Cargo.lock`（2 增/2 删）和 `MODULE.bazel.lock`（1 增/1 删），没有修改神经模型、冻结来源、CI 语义或业务代码。
- 真实新依赖：`cookie 0.18.3`；Cargo.lock Git blob `e5d61c8f7478700f481a35b1902160089ee80b64`，`MODULE.bazel.lock` Git blob `b6bdf22e077f44b019089f827033b02fda38a449`。具体 checksum 保留在 Cargo 原生锁文件中，并非手写修补。
- 独立诊断分支 `diagnostic/hcsn-7032-cookie-two-locks-20261123` 的 `e1263c6b1e57a2ec2d4f995a846571475b830e21` 使用固定 `b1af67a` 检出重建。原 Actions [45165787601](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/45165787601) 已**终态 success**：原 `cargo-deny` [137662266510](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/45165787601/job/137662266510)、原 `cargo update -p cookie@0.18.2 --precise 0.18.3` 冷重建和 `cargo check --locked` [137662265781](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/45165787601/job/137662265781)、Bazel 锁重建与原 lock 检查 [137662266508](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/45165787601/job/137662266508) **三项分别 success**。原安全作业末尾明确 `advisories ok, bans ok, licenses ok, sources ok`；仍有非阻断的 yanked 警告，不伪称警告消失。
- 对应原始工件：Cargo 重建 `14813713850`、Bazel 重建 `14814623510`，附 GitHub Actions 原日志与文件哈希。**这只确认该两锁补丁在 #7032 精确图上的安全/生成器三门；不能把原科学 head 的红门回写为绿，亦不是任何全仓/Windows/Q24/Agentd 产品资格。**

## main 的不同依赖图：lock 验证成功，原安全门仍失败

- 冻结 main `732e934ba496d90fbe042b8d41d479ef901643e5` 上的独立候选 [`86d13925f313caaca0e674e47eb6c89a932d9976`](https://github.com/TrillionniumFoundation/hepta-private-ci/commit/86d13925f313caaca0e674e47eb6c89a932d9976) 亦**只修改两个锁文件**；Cargo blob `fe57c533e45e4e0b549da17c9a1ec2a8e21d34f1`，Bazel blob `f2b6b85daad2e5e58ea849943d825b0feac74b4d`，都包含 `cookie 0.18.3`。不能把另一个分支锁图移植过来。
- 诊断分支 `diagnostic/default-cookie-verify-732e-20261123` head `7fb858bf3e62b5b35aabe866d6a6b9fc71ba5afd` 的 [45165845066](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/45165845066) **总失败**。其中原提交锁/Bazel 检查及 `cargo check --locked --package cookie@0.18.3` [137662452184](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/45165845066/job/137662452184) **success**，但真实原 `cargo-deny` [137662452404](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/45165845066/job/137662452404) **failure**。原日志除 cookie 之外仍列多项 RUSTSEC advisories（含 `RUSTSEC-2026-0592`）及 yanked 项，末尾 `advisories FAILED, bans ok, licenses ok, sources ok`。不允许通过 suppress/ignore 伪造准入。

## 签收边界

局部仅可签收“#7032 的 `cookie 0.18.3` 双锁候选在三个具名原生作业上通过”。#7032、main 或任何受保护分支的正式整体安全资格、原 Windows 四项生产隔离、Q24 500ms 长尾、Agentd 严格 101、原全仓跨平台以及冻结媒体采纳检验依旧分别 HOLD。下一步先核对其他现有分支及原作业是否已覆盖 main 的剩余安全公告，勿重复派发或取消安全门。未合并/未发布/未替换历史原件。
