# e327 的 daemon 原生验收

正式作业使用 e3277e96 原源码，原 JUnit 逐例复核出普通测试 2,849/2,849、实际 Root 测试 68/68，两个 XML 都无跳过、失败或错误。原特定学习所有者名册 202 项也核对完成。后续维护的 fix 步骤成功，固定所登记基址的 fmt 命令退出 2。格式器无法确定一份历史源证据中继承 edition 的 Cargo.toml 所属工作区。作业及整套维护最终失败。原始归档包含 49 个成员、18,171,364 字节，SHA-256 为 0e0596308ecaffd28175048843c78ae7d5a37b26c00e3b76bffb0d09909fd6fc。[原生与维护原作业](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/45130787310/job/137545550941)

original-members.zip 保留原归档中的两个完整 JUnit XML、原格式化输出及各阶段机器收据。用 `python verify.py original-members.zip` 可以重算 result.json。同一复算程序对完整原 ZIP 与此成员子集已分别得到字节相同的输出。该运行与 MemoryCell 的 1,552 项是不同工作流，不能把两者相加当成不同测试数。
