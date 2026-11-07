# R31 原始工作区门：完整闭合证据

原 source53 默认工作区门已自然通过：**20,228 个唯一测试身份全部 PASS，0 FAIL、0 TIMEOUT，130 reported skip**。原命令为 `just test --locked --retries 0`，由本次实际 metadata 确认默认 193 个成员；没有新增 package selector、filter、feature、ignore 或 retry。

原 tests raw、effective、outer 返回均为 0。nextest 执行 1643.187 秒，含构建等的 wall 为 1854.4279615879059 秒。Starting 的 366 binaries 与实际出现执行行的 323 个 binary 身份组分别记录。完整日志、原 rows、原 R29 的 20,228 个身份集合逐项相符；当前无重复身份、无 footer 失败重述、无失败块。

## 来源与复核

- [CLOSURE.json](CLOSURE.json)：门禁结果、来源、精确 pins 与资格边界。
- [INDEPENDENT-READBACK.json](INDEPENDENT-READBACK.json)：独立 reader 首次纯本地执行的完整结果。
- [ROOT-ARCHIVE-READBACK.json](reviews/ROOT-ARCHIVE-READBACK.json)：root 另一实现的独立核验。
- [原归档](archive/checkpoint-r31-closed.tar.gz)：4,484,123 字节，SHA256 `87afd6c49a3c753b90c8e53b3b70988f2964352fcf2daf0ed85c536ac6f77563`，353 regular members / 352 INDEX rows。
- [SOURCE-DESTINATION-MAPPING.json](SOURCE-DESTINATION-MAPPING.json)：每份原字节及压缩、去重后的实际位置。
- [ORIGINAL-MEMBER-MAPPING.json](ORIGINAL-MEMBER-MAPPING.json)：353 个原归档成员的完整保全映射。
- [CLOSURE-MAPPING.json](CLOSURE-MAPPING.json)：原审计内部相对路径的定位规则。
- [ATTACHMENT-MANIFEST.json](ATTACHMENT-MANIFEST.json)：最终附件逐文件 bytes/SHA256/Git blob。

全部 197 个源码的 SHA256、Git blob 和模式均从归档重新核验，原 source52 的 195 行和新增的两个 source53 诊断文件关系保持。源码仅在完整原归档中存放；156 个非源码成员另行保全。大 JSON、日志和文本只作 mtime=0 gzip，无损解压逐项相等；大件重复字节可共用一个实际附件，通过映射定位。原报告的历史 null/false/pending 字段和初稿修正记录均未改写。

本组包含惰性 runner、实际 binding/授权、原启动记录、完整闭合原件/controller、exporter 初稿和修正/静态审阅/实际授权及独立导出回执。69 个传输分块的 base64 内容未重复复制；原 whole-file 信息、传输读回、完整 SHA/Git blob 和原归档仍在。原归档 Git blob `693da6d9414f88c1620516a28958c518ac924978` 的实际创建响应及固定登记快照保留。

## 结果边界

source53 保持 **diagnostic_only=true、behavior_repair_claimed=false**。R29/source52 原 Bedrock FAIL 10.643 秒仍然保留；R31 同一 ID PASS 0.354 秒是本次观察，不能仅据添加诊断日志和后续通过宣称证明了行为修复。R28 历史项目门、R30 同源项目门与 R31 默认工作区门分别保存，不累加计数。

exporter 的自然 0 只表示归档成功，不替代原工作区退出码。本组不含也不授权 fix/fmt；不宣称格式化后资格、全部 feature、全部平台或外部服务通过。科学结论继续 **HOLD**，权限边界保持 **DENY_ALL**。共享文件系统空间采样不当作本门独占资源成本。
