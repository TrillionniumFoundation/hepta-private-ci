# 840 自动CI与机械格式后继：可恢复交付

20份ASCII base64分片无损保存XZ/CRC64归档，包含79个成员、17,928,190 B。原840两次完整CI API、两job完整console/MCP、四官方ZIP/XML、42件作者冻件及FREEZE、15件独审增量及manifest均在包内。完整原console仅归档一次；Windows 10,482个CR保留。临时artifact下载URL未归档。

原source840/treeb38范围内，两平台各3个Supervisor指定integration tests和14个Agentd protocol tests通过，Strict Supervisor Clippy通过；两个job最终均因formatter失败。六个新Unix unit tests和原paired_process_product不在原选择内，未授予执行资格。

实际机械候选tree25020dc30888fa3ffa6f6e8d1073d91edded1756仅3叶变化；删除map_err两枚冗余花括号和Termios一枚可选末逗号明确保留，其他compact字符、literal/comment、参数、断言和预算相同。实际正式独审ef03d24a5f8a16c598f0dab38044436810d0a562接受该静态范围。候选及任何发布后继仍需自身原自动CI，不转授旧840通过。

```bash
python3 restore_verify.py --root <交付目录> --output <不存在的新目录>
```

恢复时验证所有分片/完整压缩归档/每个成员的bytes、Git blob与SHA256，并实际重放两组Python/Git静态审阅及原API/console/ZIP/XML校验。期望完整离线stdout24,704 B、Git9973975c41a68159c0e148c08b9704cf34f07414。此过程不会执行Rust、Cargo、Bazel或平台原生测试，也不访问CI或改变ref。

这次没有关闭任何blocker；旧09:30包不变。归档自身Git hash是计算身份，不声称它是独立已GET的Git blob；实际分片和所有登记对象由registry列明。
