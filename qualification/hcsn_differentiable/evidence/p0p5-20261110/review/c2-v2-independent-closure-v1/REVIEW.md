# C2 v2 独立静态关闭审查

**冻结 v2 直接修复了前次独立反例中的三项结构问题，未发现该修订引入新的阻断。** 被审源码为 `c2-feasibility-v2/c2_boundary.py`，SHA256 `177a23a3d0502a79912efdd2a14a365bc716961698a6949bb45d380ba147e6dd`。这是静态与原始验证回执审查，没有重跑训练或重复 owner 的 21 项测试。

| 前次问题 | v2 实现 | 关闭范围 |
|---|---|---|
| 末尾 stale 清零可能掩盖更早已触 plateau | 新增 `first_plateau_epoch`；terminal_guard 从完整 retained history 重算状态，与 boundary 缓存严格一致后，再要求历史从未触发停止。 | 修复所构造的 40-epoch 元数据反例；没有因此认定 native 原轨迹有错。 |
| 首个累计 clock 可为负 | 初始单调性下界改为 `(0.0, 0.0)`，继续要求 finite/nondecreasing。 | 累计 wall/CPU 均拒绝负值，允许精确零。 |
| AdamW 二阶矩仅要求有限 | 对每个参数的 `exp_avg_sq` 明确要求全部非负。 | 适用于当前 HCSN FP64 实数状态；若以后扩展到复数，需另外定义实/虚通道规则。 |

读取的 owner 原始 `validation/RESULT.json` 与 stderr 记录了 21 项通过、源前后 SHA 相同，完整子进程 wall 为 3.3880163450012333 秒、waited child CPU 为 4.165834 秒；该验证确实含新增的三类拒绝用例。这些是 owner 的执行成本，本次没有再执行一次测试，也没有把记录复制当作新的通过次数。

v1 源码、18-test 记录、第一次测试失败、独立三反例和原 ZIP 保留。v2 验证绑定独立反例 JSON SHA `1e20f69ed02476eca3b9812c81f2c770d9bd641f0f090b00d32407ed73dafd85`。新 v2 包为 269574 bytes，SHA256 `cea3eb1509ecec51174b0c86b0f60b5ed4eb938d0739972bcaa6c46f94fb5e96`；CRC、唯一安全路径与 manifest 的字节映射在本审查中另行核对。

## 仍然保留的准入边界

它仍是结构 validator 和方案，不是 runner、snapshot 任务或原生恢复授权。`execution_authorized` 保持 false；完整 source/data/runtime、父终态、checkpoint 文件、journal 和实际 outer ceiling 的来源绑定仍需要另一个独立执行步骤。没有读取生产六个 HCSN 的活跃 checkpoint，没有启动 C2，没有访问 E，也没有通过续训结构测试扩大 P1 数值覆盖。

原父完整 outer wall、被舍弃的 partial work、所有冷启动/验证/失败成本不退款。原阶段的实际 ceiling 与原预算截点仍独立；12 小时/200 epoch 是明确另列的自适应后续提案，不能回填原 4 小时资源机会。未测量的完整 parent exit CPU 仍不能被虚构。
