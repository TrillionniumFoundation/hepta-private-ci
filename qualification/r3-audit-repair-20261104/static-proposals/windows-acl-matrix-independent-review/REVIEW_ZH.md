# Windows ACL 幂等与删除四格独立窄审

**结论：静态接受，原 Windows 执行门槛仍待完成。未发现需要先修改候选源码的阻断。**

本次核查 ACL V2（`a7b977f7`）和四格 V2（`ba0f8c1d`），独立读取并核对锁定的 windows-sys 0.52.0 API，完成四种真实 Git 重建及 8 个后像的字节比较。未编译、运行 Windows、进行权限实验或改变共享源码/引用。

| 审查面 | 结论与界限 |
|---|---|
| API 与编译前提 | 新 API、类型和现有 Cargo features 静态匹配。实际 Windows 编译与文件系统行为仍必须验证。 |
| 句柄权限与同对象 | 完整 ACL 路径仅取 READ_CONTROL；需要修复时以 ReOpenFile 对原对象取得 WRITE_DAC，再经该句柄写 DACL。不会通过第二次路径查找选取另一对象。它不提供并发 DACL 写者之间的序列化。 |
| 完整匹配 | 原公开递归查询不变；私有修复判断接受同 SID、各自完整的 effective 与 inherit-only 规范化对，不拼接两个残缺 mask，也不越过 allow/inherited 边界。 |
| 原断言与实物控制 | 原 ACL/token 测试全文与 legacy 正文逐字保留。新四格保持原生产 token/legacy 路径，实际检查对象 ID、ACL、内容和最终删除结果；Everyone 仅出现在测试对象 ACL，未加入 restricting capability。 |

三个原严格失败用例仍是验收门：partial delete deny repair、broad identity ACE 下的 capability 删除限制，以及 legacy writable roots / outside / `.git` 删除限制。ACL 幂等通过不等于删除漏洞修复。新增 3 个 ACL 控制与 2 个删除四格控制都须在原 Windows target 真正执行并保留完整日志/每次尝试。

集成只使用 manifest 的 8 个精确路径。四格 candidate 目录有未注册的旧 V1 helper，不能整目录复制。完整 API 锚点、后像哈希、原用例名与 pending 边界见 accompanying JSON。
