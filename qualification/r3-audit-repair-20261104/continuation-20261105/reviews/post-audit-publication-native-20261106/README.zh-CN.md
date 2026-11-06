# 审计发布回执与后续原生增量

本包保留实际审计提交 `fc10fbef82ec8e1a7db511c06d865c147200f1fc` 的创建、完整 GET、CAS ref 更新和更新后 GET。其 parent 为 `46fd74d98c1cef42e1439920f9ca83361481b3d8`，tree 为 `3cbdfada435378fb080f1e5f9359e4f34d70f74c`。完整树有 14,670 叶、2,276 个非根目录；各目录的 Git tree hash 已重算，报告文件与实际树条目一致。23 个原 blocker ID 与 exit 字面保持，仅 B23 相对前一账本转为 CLOSED_SCOPED。

当前账本仍为 **16 CLOSED_SCOPED / 6 OPEN / 1 SCIENTIFIC_HOLD**。本包不新增 blocker 闭合，不授予全候选或全平台资格。

## 已执行的追加动作

- PR #4797 和 #4884 已实际同步审计链接与当前资格边界。完整旧正文保留为新正文后缀；更新前后 head、base、merge 和 Draft/open 状态一致。
- B23 collector v3 的普通 pull_request run `42164668625` / job `127718228723` 整体 success。两官方 ZIP 原字节共 47 个成员；完整 8 log + 8 XML 可恢复。307P/0F/1I、三原 signal 父测试及两原 drain 测试通过。固定源码全部 10,582 产品叶不变。八产品动作 remote/noncache；八 XML 辅助动作中六个 remote/noncache、两个 remote cache hit，分别列示。每份日志通过自己的 XML 辅助动作输入 digest 绑定，每份 XML 通过该动作输出 digest 绑定；产品 spawn 未直接记录 test.log output digest，因此不声称直接产品输出摘要绑定。
- Windows 格式修复 head `18bbef4f61c6086f145bdb6f7acbf82127741a14` 的原 repo-check job `127731162050` success，完整日志中原 `just fmt-check` 成功；其 head/ref/PR/merge/tree 绑定已核。早期 `340fbc06` 上两项 setup-error 测试的通过没有转授给新 head。
- Windows state EOF 的阻塞锁草稿正式 **REJECT_PUBLICATION**。固定源码、原 EOF 单事件与独立 ACL error 5、未执行草稿及替代设计义务在独立 registry `4404e9d44ee8b1e070a6106f2fba1779991bb7db` 保留；root 已恢复 117 成员并重放得到相同 3,429 B 静态输出。该拒绝决定不是产品修复。
- 两份独立正式审阅原件保留：root followup 为 `4423b3169ab036951dfbf9736d435e68fc41458a`，新 B23 native 为 `fdc684cee0eec8d6387020e666bb915e4fad6e83`。各自独立重放 exit 0、stderr 0，并核对原冻结 stdout。

## 观察分母

2026-11-06 **05:52:07–05:52:12 UTC** 的追加读取仅覆盖四个固定 run，全部 latest-attempt jobs 页完整，合计 73 jobs：

| 固定来源 | Run | Jobs | 成功 / 失败 / 运行中 / 跳过 |
|---|---:|---:|---|
| B21 collector `84cc7345` | 42164663819 | 1 | 0 / 0 / 1 / 0 |
| B23 collector `2ac89eaf` | 42164668625 | 1 | 1 / 0 / 0 / 0 |
| Windows fmt `18bbef4f` | 42166252146 | 35 | 23 / 3 / 5 / 4 |
| PTY candidate `8075eb36` | 42167168039 | 36 | 25 / 5 / 2 / 4 |

这是有界、非原子的增量窗口，不覆盖全部 workflow，不替换 C1 的七 head、46 run、214 job 全量切面；主候选原 93-job 终态与七个执行失败、两个汇总失败仍保留。B21/PTY 的运行中状态属于上述窗口，不表示未来完成。

## 重放

`python verify_packet.py` 会核对分片、完整 ZIP 与全部成员，恢复到隔离目录，重算完整审计树、核对原 exit 与正文后缀、固定四 run/job 绑定，并重放 B23 原始证据 verifier。它需要 Python 与系统 zstd，不执行产品测试、不触发 CI、不写任何远端 ref。

完整 payload、原官方 ZIP、verifier 早期错误历史及实际重放结果保留；临时签名下载 URL 不进入本包。旧 B23 collector 失败与缺 XML 仍保留在此前证据，新 XML 不回填旧运行。
