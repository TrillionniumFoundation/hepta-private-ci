# v7 内存观测模块：独立只读代码审查

本审查读取 `process_memory.py` 与 `probe_memory.py`，未修改被审查代码，未重新运行探针或测试。结论针对阅读到的版本；若作者随后修复，必须以修复后的证据另行说明，不能把本报告当作修复版本已通过的证明。

## 具体问题 1：已知存活子进程没有约束“完整族”声明

**优先级：P1，可能导致覆盖状态被高估。**

`Observer.sample_family(root)` 先枚举族、采样，然后再次枚举，两个列表相等就设置 `full_descendant_coverage=True`。它没有接受或核对 caller 已通过握手登记的存活进程集合。

`probe_memory.parent` 明知 parent、child、grandchild 三者都在等待结束命令，却仅通过 `all(sample['available'] for sample in families)` 设置 `full_family_measurement_available`。该判断没有要求枚举结果包含这三个已知身份。

因此，若 `children` 文件可以读取但稳定漏报，例如两次都返回空列表，严格族路径将只采样 root，并宣称完整覆盖。与此同时，registered-set 路径即使成功测到三个受控进程，也不会否决该“完整族”声明。该问题不要求伪造 RSS 数字；它是清单完整性与已知证据没有连接的问题。

当前环境若因不可读取 children 接口而返回 unavailable，这个拒绝结果是正确的。该次探针的失败关闭行为不能证明“可读但稳定漏报”的路径也已封闭。

### 建议修复

- 为 family 采样提供 `required_members` 或等价的已登记、预期存活身份清单。
- 要求采样前后两次族枚举都包含这些完整身份，不只匹配 PID 数量。发现同 PID 的不同 start time、父关系或 namespace 映射时拒绝。
- 受控三进程探针应比较所发现的精确集合与预期集合；缺任意已知成员时，family 覆盖必须 unavailable。
- 对真实服务，登记清单应覆盖 supervisor、encoder worker 及已知辅助进程，并明确登记清单不能排除未知短命后代。

即使加上已知身份下界，前后两次相等也不是原子的、对整个时间区间完备的进程族证明。进程可以在两次枚举间生灭。因此字段和报告应明确它证明“前后枚举一致、所有已知预期身份纳入”，并继续声明顺序读数、短峰值与短命后代的采样限制。

## 具体问题 2：探针握手缺少超时，失败时清理不保证有界

**优先级：P2，影响工具可靠性与受控成本边界。**

`read_line(pipe)` 直接阻塞在 `pipe.readline()`；parent 等 child、child 等 grandchild 的握手和结束响应均无超时。如果已启动的受控子进程卡住但没有关闭 stdout，探针可能无限等待，不会进入后续 `finally`。

异常清理虽有 `child.wait(timeout=10)`，但超时之后没有保证受控子进程及其后代被终止和回收；这可能留下仍占用资源的探针家族。现有成功探针不能覆盖这个故障路径。

### 建议修复

为握手、结束响应和退出分别规定有界超时。只对本工具实际拥有的进程句柄或明确建立的独立进程组进行终止与回收；不能按扫描出的 mounted-proc PID 杀进程。失败输出应保留 timeout、被回收的身份、退出状态和不完整成本范围。不得用猜测的 RSS 或默认完整覆盖填补超时结果。

## 阅读范围内没有发现的原 v6 错误重现

以下是代码结构评价，不能替代运行证据：

- `own_identity` 从 `/proc/self` 得到 mounted-proc PID，并用 `NSpid` 尾端绑定当前 namespace PID。
- 自有子进程通过父进程实际获得的 spawn PID、namespace 深度、父关系和 start ticks 绑定；没有直接将 Popen PID 当作 mounted-proc 路径。
- RSS 读取前后检查身份，PID 复用、重挂父关系或身份变化会拒绝。
- children 读取失败会成为 unavailable，registered-set 路径始终将 `full_descendant_coverage` 设为 false。
- 结果明确 RSS 求和不等于独占物理内存，顺序读取不构成原子快照。

因此，这个实现针对 v6 的 PID/proc 错配已经增加了正确的身份绑定。当前尚需封闭的是已知清单与完整族声明之间的缺口，以及探针自身的有界故障路径。
