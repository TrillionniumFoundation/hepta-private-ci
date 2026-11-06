# R29 发布读回补充

本组记录 R29 已闭合失败证据的 Git 对象发布事实，不是新的测试执行或 artifact checkpoint。原工作区测试仍是 source52、自然 exit 100、20,227 PASS / 1 FAIL / 0 TIMEOUT，130 项为原输出的 reported skips。

R29 正式组保持冻结的 202 文件 / 6,133,028 字节。逐路径核验了全部本地原始字节、SHA256、Git blob，以及 97 次实际新建响应与 105 次现有实际 Git 对象复用。15 个二进制附件中，原始 archive 已登记；本次另登记 14 条路径。当前固定 ledger 为 53 source commits / 222 binary attachment paths / 6 artifact checkpoints，没有创建发布分支或 PR。

archive-publication 保留原输入适配错误和纠正响应：首次 Git blob 请求误构成空输入，其返回空 blob 未注册为 archive；重新构成并双重校验的完整 3,334,510 字节 archive 对应 4147c2510b0f1a462d121eb211d7ac073274fe38。原空输入响应和纠正说明都保留。文件信息响应的结构适配记录也保留，未改动 archive 或原生执行。

本组不证明 source53 的项目或工作区测试通过，不证明 Bedrock 超时根因已经修复。科学结论继续 HOLD，authority 继续 DENY_ALL。
