# hepta-private-ci 当前审计入口

最近已确认：**新七提交候选已发布到现有 Draft；Linux PTY 原 29 项及修整完成；Mac 包装器原 57 项修前 3 FAIL、修后 57 PASS。** 原 23 项台账仍是 **8 项限定闭合、14 项开放、1 项科学采用 HOLD**，全部闭合尚未达成。

| 阅读入口 | 内容 |
| --- | --- |
| [完整项目审计](../CURRENT_AUDIT_PROGRESS.zh-CN.md) | 全仓清单、源码、原测试、科研和外部接受边界 |
| [发展方向与后续计划](../PROJECT_DIRECTION_AND_PLAN.zh-CN.md) | 40 模块、91 工作包及近期 P0.8D / INT-2 主线 |
| [09:12 续批进展快照](CONTINUATION_PROGRESS_V2.zh-CN.md) | 七提交修复、原 CI 最后结果、P4 依赖失败和逐项退出要求 |
| [Mac 原 57 项资格](MAC_WRAPPER_QUALIFICATION.zh-CN.md) | 完整修前/修后原件、真实 Git 投影和限定范围通过 |
| [原 23 项退出条件](../current-blockers.json) | 原退出条件与状态分类，保持不变 |
| [产品发布回执](reviews/product-publication-receipt-v1.json) | head、base、merge、lease 与 Draft 回读 |

## 当前继续执行的工作

产品头为 `5b6331250ff459033bd44d1a95daec70131277cc`，树为 `b26598d0d97d8d51e723bb5582137315f2174d35`；原基线仍为 `63652be658ebed8d3052eb789b951793384fd5e4`。新头的原 19 条工作流已触发，09:30 左右仍未取得新头的实际 runner 或测试结果。新 `blocking-ci` 页面明确等待旧同组运行完成；其他 16 条队列的原因仍未知。

新主机已取得匹配的官方 V8、OpenSSL 和 libcap 构建输入。P4 v2 的六个 helper 与完整 metadata 曾实际成功，完整 catalog 编译因缺 libcap 退出 101；首次 OpenSSL 缺件及所有失败都保留。新增 libcap 输入后，为满足现有 V6 的单一实际环境合同，继续在同一新环境原样执行 helper build → metadata → 完整 catalog，复用任务内缓存，零测试执行。成功的 BUILD_ONLY 基线仍须实际产生，然后才能绑定 B foundation 的原正负控。

后续顺序为原平台具名缺口、B16 正常入口与效果、main 整合和真实 UI 接受，再推进共享计算、可靠 Memory、独立科学采用及 Bao / Chain / HIA 外部接受。科学 HOLD 和外部缺口由相应的新证据关闭。
