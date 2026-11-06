# B11 最小修复切口复核 V2：完整便携证据包

直接阅读 `REVIEW.v2.zh-CN.md`。本包只读绑定固定源码、既有 native10/11 MIC 原记录和既有 native13 机制事实，B11 保持 OPEN；没有新增 native、CI、产品源或 ref/PR 操作。单纯 Low 的同级外部删除物理反证不等于所有 token/API 手段不可能，未验证的兼容性明确保留 UNKNOWN。

V1 107 个核心文件逐字节保留，V2 加入 MIC 恢复原件/报告/离线校验；`V1_TO_V2.json` 记录两版关系及旧包身份。旧 transport 不重复嵌入，本包已独立包含所需原件。固定 99a 比较锚不声称 ac18 最新 native 资格。注释候选仅作为独立 postimage 保存，不进入当前源。

## 恢复并复验

```
python verify_packet.py <本目录> <一个不存在的输出目录>
```

标准库 Python 即可。脚本从各 base64 part 完整还原 gzip/tar，逐一核 manifest 的字节数/Git/SHA256/mode，然后在独立恢复目录执行两个只读 Python 检查器，要求完整 stdout 与冻结原件逐字节相同。MIC 检查器还会从原 full GET 回执恢复旧实际注册包的全部 41 成员，验证完整 9cb 树、14 个来源文件和 native10/11 原 log/XML。不可解析的交错记录与一次错误 Git lookup 均保留，不拼接补造。

本包不是 Rust 编译、formatter、Cargo/Bazel、Windows native 或产品安全资格。实际对象登记只证明本次保存与完整回读一致，不改变原退出条件。普通可逆注释纠正不需额外审批；实际扩展权限/执行边界才须按 B11 原 literal exit 明确升级。

`registry.actual.json` 列直接可引用仓库路径及实际对象身份，`registry.self.actual.json` 记录其自身创建/完整回读；`tree-elements.json` 供根在审计分支追加。所有 payload 均为 UTF-8 文本或无损 base64 分片，完整原 source/log/JSON 保存在包内。没有保存下载凭据或临时签名 URL。
