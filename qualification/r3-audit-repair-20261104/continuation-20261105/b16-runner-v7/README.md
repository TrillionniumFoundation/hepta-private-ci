# B16 V7 — 原完整 catalog 的 ignored 语义修正

V7 只修复自有 harness 对完整 nextest catalog 的错误解释。P4 的三个原始构建、元数据和 catalog 命令都已返回 0；随后派生解析把全部用例都要求为 matches，误拒绝了项目原有的 57 个 ignored 用例。冻结 V6 的 build-only 消费端有同一错误。两个旧失败和旧静态审查记录均保留，本修订明确更正旧审查遗漏。

## 精确接受范围

仅接受以下完整形态：

| 原用例属性 | 完整 filter-match 对象 | 固定原名单 |
|---|---|---:|
| ignored is False | {"status":"matches"} | 19,506 |
| ignored is True | {"status":"mismatch","reason":"ignored"} | 57 |

除此之外的形态全部拒绝。解析后的 (binary_id, name, ignored) 完整 Counter 必须与冻结 fb9 原 catalog 逐条相等，不能仅保持总数。原件无损存入 observed-original-A-catalog.json；其 bzip2/base64 内容解码后是完整的 2,846,923 字节原文件，保留原历史路径与来源，未把它重标为新主机的构建或测试。

当前 ai395 的原 catalog 为 2,828,836 字节，SHA256 d4ca608073c2508e8ad5302b1188c7d2e21c6bf221a17688d77f625087e8d3f6。已经独立重开完整原件，对比旧 fb9 的全部 19,563 条 Counter 和两种完整 filter 字典，结果完全相等。

## 必要的云端验证

旧 V6 runtime 配上真实原 catalog，原第一个守卫控制精确报出 build-only catalog was filtered，不是导入失败。V7 的四个原控制正文逐字保留；仅将其虚构的单例 matches fixture 改为真实完整 testcase 映射。再增加两个必要控制，分别拒绝六种错误过滤形态，以及三个保持总数的换名或 ignored 归属交换。

六个云端 Python 控制实际全部通过，耗时 7.924 秒。完整 stdout、stderr、status 位于 cloud-verification-v1/。这不是原生项目测试资格，不运行 Cargo、Bazel 或 B16 生产控制。完整 V6→V7 patch 已在独立 Git 目录实际 apply，29 个后像精确相等。

## 不变边界

22 个既有输入逐字不变，包括所有 source payload、五个 epoch、物理断言、negative parser、SourceGuard、negative_with_finally、原始命令、0 retry、锁门和预算。旧 reuse_final_A 分支的文件及入口不变。三份模板仍 execute=false、approval_reference=null。

内部执行 stage 编号属于 B16 内部阶段，不是原始 23 项 blocker 的编号；本修订不改变这些 blocker 的状态或退出条件。

## 具体 foundation 消费绑定

下一次绑定必须使用实际当前主机的完整 BUILD_ONLY_CURRENT_HOST baseline，保持 tests_executed=false 和 test_qualification=false，并同时保留历史 ROG fb9 测试收据及 fb9→4a hygiene 审查。不得重写旧 ROG 路径或把新主机构建叫作 A 测试通过。

消费者继续要求实际 4a 源、20fd 普通 HEAD、当前普通 index、双锁、工具和完整有效环境；真实三条原命令、六个原 source guard、193/1501 metadata 图、363 个程序和 33 个 helper 全部身份与关联。P4 的只读收尾可以单独记录后续当前物理文件及 SDK 守卫，但不能重标旧命令或覆盖原 outer=1 的记录。

本版本没有 enabled binding，也不填写将来的哈希。foundation 的 22,000,000,000 字节启动条件与每命令 8,000,000,000 字节保留量原样；这仍是有条件尝试门，不是峰值容量保证。后续 driver、pool、checkpoint 的隔离顺序及原预算保持不变。
