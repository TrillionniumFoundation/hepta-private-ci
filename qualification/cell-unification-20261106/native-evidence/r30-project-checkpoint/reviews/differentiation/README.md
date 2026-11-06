# R30 独立闭合读回

本组独立读取了 R30 已闭合的 **19 件成功原件和自然终态**，完整解析原 tests.log，并逐字重建执行结果 rows。只运行本地只读 Python 解析器；没有导入 gate runner，没有执行 native、Rust、metadata、fix、fmt 或工具查询。

| 检查 | 原件读回 |
| --- | --- |
| Source53 | f74be175de66a4b351cd239d39d98cd34fe9cc1b / 440d4a8e09af4009e4d9ea067388826308da8803 |
| Strict | raw/effective 0；189.01348495483398 秒 |
| 完整 app-server tests | raw/effective 0；含构建等 972.5199975967407 秒 |
| Nextest | 404.442 秒；1,345 unique PASS、0 FAIL、0 TIMEOUT；2 reported skips |
| 身份验收 | 与固定原 R29 app-server 1,345 身份完全相等；缺失 0、额外 0 |
| Binary 口径 | Starting 宣布 6 binaries；有执行行的 3 组为 lib 321、all 1,020、bin 4 条测试 |
| 日志末尾重复 | 0；解析器始终排除 Summary 后复述 |
| 外层控制器 | 原 job 1a1b25b399f-fc05-7daa，自然 succeeded/0；stdout 5,097 B、stderr 0 B 连续片段读回完整 |
| 源码守卫 | 原完整 197 manifest、各阶段源守卫、native HEAD bef6fa…和双锁一致 |

原 Bedrock 用例在 R29 中仍记录 FAIL / 10.643 秒；R30 当前观测为 PASS / 0.352 秒，两个观测并列。Source53 保持 diagnostic_only=true、behavior_repair_claimed=false。本项目门通过不替代独立工作区门，也不单独授予 finalizer 执行资格。

## 文件入口

- [CLOSURE-SUMMARY.json](CLOSURE-SUMMARY.json)：简明计数、二进制口径、阶段耗时与范围。
- [INDEPENDENT-READBACK.json](closed-readback-v1/INDEPENDENT-READBACK.json)：20 原件完整 pins、raw/receipt/resources/source guards/自然终态和身份集合。
- [EXECUTED-ROWS.json](closed-readback-v1/EXECUTED-ROWS.json)：从原日志独立重建，319,763 B，SHA 983ea2651aa1564afbc6ab901012112cc602bf727441bdc014c1bc611c2b777f；与 native 原 rows 逐字相等。
- [CONTROLLER-READBACK.json](CONTROLLER-READBACK.json)：原 direct-file launch、授权、连续 offset/hex/text、自然终态和六条阶段 announce 的交叉读回。size 按流当时总长度解释，没有当作片段长度。
- [review_closed.py](review_closed.py)及[review_controller.py](review_controller.py)：纯本地复算工具；不导入或执行 runner。
- [INPUT-REFERENCES.json](INPUT-REFERENCES.json)：固定 baseline、实际 runner、授权、manifest、producer/consumer 和闭合原件的来源引用。
- [LOCAL-EXECUTION.json](LOCAL-EXECUTION.json)：两次真实本地解析调用的工具回执。

## 明确边界

此次未等待大归档，所以没有在本组重新读取 197 份 raw source 或离线重建 Git tree；该边界在主报告中为 REGISTERED_MANIFEST_AND_CLOSED_NATIVE_GUARDS_ONLY / full_export_bytes_pending=true。后续归档级字节证明应另附，不能回写本次范围。两条 reported skip 没有被推导成逐例 skip 身份；共享主机空闲空间也没有被解释为此门独占的资源成本。

旧 R29/R26/R24 失败、旧启动快照和所有原件保持不变。此组没有发布或改写正式根报告、INDEX、ledger、源码或任何执行环境。
