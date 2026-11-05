# 当前审计与修复状态

**原 23 项仍为 8 项限定范围闭合、14 项开放、1 项科学 HOLD；尚未取得全部 blocker 闭合或 main 合并资格。**

产品修复已经发布到 [Draft PR #4797](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/4797)，当前固定 head 为 `5b6331250ff459033bd44d1a95daec70131277cc`，代码 tree 为 `b26598d0d97d8d51e723bb5582137315f2174d35`。本轮七个提交涉及十个文件；旧失败和修复回执分别保留。

## 最近已经完成

- macOS Bash 3.2 的原 wrapper 57 用例：修复前原 3 个失败重现，修复后 57 PASS、0 跳过/重试。13 个精确文件的真实 Git 投影及全部 74 份原件已经独立核验。
- Linux 原 PTY 29 用例全部通过；原 fix/fmt 和两个 diff-check 成功，测试专用诊断及实际 fmt 改动已经提交。Intel PTY 的原失败原因和原平台资格继续开放。
- ai395 的 V8、OpenSSL、libcap 构建前置已解决。原六 helper build、完整 metadata、无过滤完整 catalog 三条命令全部成功。19,506 个可执行用例、57 个原 ignored、193 成员、1,501 图节点和 363+33 程序身份均保持原契约。
- 原目录解析器误拒绝 ignored 的失败已定位并保留。只读 completion 成功取得 396 个当前产物身份，没有重跑成功命令、没有执行 B 组测试。V7 使用完整原名单修正这一判断，保持原执行门；Git 工具身份也已独立补齐。
- 新提交的 Intel / Windows operator 原 CI 分别实际通过 33 / 40 个原用例，含真实 OpenSSH 对照。Windows 普通业务库在实际 base-merge 上通过 118 个具名用例，保留库在产品 head 上通过 532 个具名用例，另有 7 个未具名跳过。完整日志与原 ZIP 分别核验，均不代替真实外部产品接受。
- 可信入口 Foundation 已实际进入 B 源码验证：首组 4 个原 SQLite 提交门控制通过、0 重试；原 216 个过滤项单列。原定反事实负控继续执行，尚未取得整个 Foundation 或 B16 的关闭资格。

## 正在推进

旧 blocking run 的单个串行等待已经解除。10:41:39 的逐 job 快照及截至 10:45:00 的完整分页中，新 19 个 workflow 有 44 个 job：38 queued、2 skipped、4 success。**工作流顶层 queued 不证明内部没有执行**；后续按逐 job 的源码身份、完整日志与原用例结果更新。新 118+532 个用例与冻结的 142 个原失败退出用例没有名字交集，不据此减少这些未验项；两项 Windows 私有目录拒绝控制另获同 head 的实际通过结果。

可信入口按已审查的 foundation → driver → pool → checkpoint → owning 顺序推进。构建收据仍只授予 BUILD_ONLY 范围；新原生结果独立记在实际任务 `1a1ab493f2b-fc05-4bfe` 下。首次启动工具超时保留；完全相同请求与操作键的对账取得 durable job，控制器实际返回 `reused=false`。原 24 个不同阳性控制、27 次规定执行、10 个负控执行、恢复规则和预算均保留。

10:14 / 10:26 的 PR 增量复核另发现 45 个新 Draft 编号与 49 条近期更新记录。它不改变原全量库存的观察时间。Windows PTY donor 的新编译失败、Windows 删除隔离的真实边界及未接生产的 Memory 候选均单独记录，没有直接并入产品。

## 阅读入口

- [本轮构建收尾、目录修正、新 CI 结果与执行计划](CONTINUATION_PROGRESS_V3.zh-CN.md)
- [原 23 项及本次进度](continuation-blocker-progress-v2.json)
- [全量项目审计](../CURRENT_AUDIT_PROGRESS.zh-CN.md)
- [项目发展方向与后续计划](../PROJECT_DIRECTION_AND_PLAN.zh-CN.md)
- [Mac wrapper 原 57 用例资格说明](MAC_WRAPPER_QUALIFICATION.zh-CN.md)
- [新 PR 增量与候选边界复核](PR_INCREMENT_20261105_1014.zh-CN.md)
- [上一批快照：发布、构建前置和原始失败](CONTINUATION_PROGRESS_V2.zh-CN.md)

原失败、取消、skip/retry、早退、缓存与未取得的证据分别记账。科学 HOLD、正常 UI/Root/provider 接受及 Bao/Chain/HIA 的真实外部接受没有因为构建或局部测试成功而关闭。
