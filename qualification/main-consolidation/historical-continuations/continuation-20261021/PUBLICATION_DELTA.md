# 发布前远端状态增量 — 2026-10-21 01:54:37 UTC

本记录补充01:35:51快照，未覆盖或改写原始执行回执。14次只读API请求覆盖
01:52:32.147–01:54:37.379 UTC；四个PR的head/base首尾一致，无观察到的race。
各集合均单页完整，但检查仍可在采集后变化。原记录见
[ci-live-publication.json](ci-live-publication.json)。

| PR / source | 观测到的全部当前head checks | 必需门禁与后续 |
| --- | --- | --- |
| #2968 / b11459f4 | 23项：4 success、17 queued、2 skipped | blocking-ci仍pending；CI required、Architecture required尚未出现。Windows private-state专项、Bazel lock proposal和Keyring lock proposal workflow成功，仅限定这些scope |
| #2969 / ca276897 | 44项：18 success、4 failure、12 in_progress、10 skipped | Architecture required已success；CI required尚未出现。cargo-deny及Windows Bazel shards1/4、2/4、3/4失败 |
| OS #224 / 49e5582d | 7项：6 success、1 in_progress | exact-kernel-ktest job118984639491仍运行；不视为全矩阵完成 |
| OS #225 / 9476f50e | 7项：6 success、1 in_progress | exact-kernel-ktest job118985116581仍运行；不转移旧head资格 |

#2968当前8个workflow run：3 success、3 queued、1 pending、1 skipped。
#2969当前5个workflow run：4 success、1 in_progress。workflow总体success不替代
所需平台scope、原始失败job复验、依赖安全总门或生产研究资格。

Reader新增Windows失败job为118977201830、118977201936、118977201768，均来自
ca276897的blocking run39524743211。状态是直接API事实；未仅凭失败名称归因到
Reader补丁或断言它们已由其他分支修复。已有本地Linux包验证仍只具有原记录范围。

**无新增合并资格；本轮merge/close/delete/force-push仍全部为0。**
研究继续SHADOW_ONLY / DENY_ALL / NO_GO。此记录没有建立回复后的后台监控。

## 新失败日志取证

01:56:50–01:57:24 UTC取得上述三个job的完整连接器解码日志。实际checkout均为
`1aeb57e168bd3c5465a386f99fd541e31c3555b3`，即ca276与base f191的合成merge。
Git wrapper readiness、sandbox helper路径、RPC错误码及matrixd socket状态等
既有故障签名重现；另有权限与其他断言失败。未发现同一code-mode-host缺失binary
panic，不能把所有失败归并到单个cargo-bin问题，也没有证据归因于Reader Python改动。

三个分片的Bazel target计数分别为84/6/47、89/15/38、90/10/45（pass/fail/skipped）；
这是目标汇总，不与Rust unit-case计数相加。出处、上下文、完整返回文本大小/SHA与
恢复URL见 [PUBLICATION_WINDOWS_FAILURES.json](PUBLICATION_WINDOWS_FAILURES.json)。
完整raw日志未纳入本交付，摘录和哈希的范围及传输完整性限制均明确保留。
