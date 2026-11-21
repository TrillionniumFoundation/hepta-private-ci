# 旧 E5 排除指纹：实际 Python 3.12.3 解析证据

本包保留 root 单次启动的 qualified_v2 解析原件、完整 PTY 输出、逐片读回回执、输入前后核验及实际差异。解析退出码为 0；此结果用于旧材料排除，不构成模型训练、原生测试、来源资格或科学收益的证据。

## 实际执行与输入

- 宿主为 desktop；固定旧 payload 来自 hepta-private-ci 的 7f790fb2f907ef9e618c3c7d233d22135ab00580。只读取既有 16 份旧材料与其保留的历史选择记录。
- 真实 `/proc/self/exe` 为 `/usr/bin/python3.12`，CPython 3.12.3，8,020,928 B；完整 SHA 与既有 qualified C 身份一致。原件同时记录 ast.py SHA。
- root 使用持久 PTY 启动原 qualified_v2 参数，外层 timeout TERM 85 秒、KILL-after 5 秒；原内层 60 秒 alarm 保留。原 H process 90 秒参数没有执行。
- 6 份输入以 create-only 方式上传，执行后长度、完整 SHA 和版本号均与上传后一致。timeout 文件执行前后信息一致；这属于文件观测，不另外宣称 timeout 的 FD 执行绑定。
- 完整终端输出为 1,419 B，含原 CRLF，与目标 output.log 全 SHA 一致。PTY 是合并终端流，不能标成分别保存的 stdout/stderr。

## 真实差异与排除范围

- 最终应使用本次实际 3.12.3 的 EXCLUSION_E5 和 FINGERPRINT_SETS；与本地 3.12.14 结果的完整字节不同。
- 9145 个函数节点和 487 个模块逐行比较：只有 pyparsing/core.py 的 `_default_start_debug_action`、pyparsing/exceptions.py 的 `ParseBaseException.explain_exception` 及其两个模块发生 AST 哈希变化；对应 dump 字节数各增加 20。没有断言具体 CPython 内部原因。
- 所有测试 AST 集合、47 份原测试片段指纹、完整源文件哈希、owner/source ID 集合相同。未对 type_params、空字段、名称或其他 AST 字段作规范化。
- 488 个 Python 内容中 487 个可解析；loguru 的 t_string.py 保留 1 个 SyntaxError（第 11 行、第 15 列）。coverage_complete 仍为 false，原始文件 SHA 与 owner/source 仍被排除。
- 16 份材料外的 agronholm/exceptiongroup PR155 仍因既有选择暴露而排除；不伪造其源文件或 AST。该集合还须与 root 的其他历史暴露集合合并。
- 文件、函数与测试片段数量表示排除覆盖范围，不是独立科学样本数。

## 原件取得方式

- EXCLUSION_E5、FINGERPRINT_SETS、MODULE_AST、FUNCTION_AST 共 4 件按固定版本完整读回，逐片及整文件 SHA 全核。
- 其余 7 件与已保留本地原字节的长度及完整 SHA 相同；它们放在 reused_local_bytes，并由实际远端 file_info 绑定。没有将这 7 件标为重新下载。
- 101 个成功二进制分片对应 102 次尝试；19 个成功 file_info 对应 20 次尝试。2 次 MCP Connection failed 原文均保留，只补取失败的同路径元数据或同版本缺失范围，没有重跑解析。
- staging 的 15 次远端调用全部成功；另保留首次大分片远端调用前的本地 JSON 请求组装错误。后续远端分片 ID、offset、长度及 SHA 没有改变。
- 完整 MCP response 保留在带原请求/时间的 envelope 内；不重复打包其另存的同内容响应副本和已解码分片文件。

## 持久化边界

冻结解析器显式 fsync 每份输出和 derived 目录；没有显式 fsync 新建 derived 目录的父目录。PTY 的 output_complete、无 capture_error 和磁盘日志全 SHA 已观察；不据此添加未观察到的掉电保证。既有脚本、原限制文案和原 H90 参数均不修改。Git 提交与 ref 由 root 独占处理。

## 包结构

按 CHUNKS.jsonl 的 offset 顺序拼接 payload 分片，整包 SHA 见 CONTAINER.json。容器为 tar.xz；MEMBERS.jsonl 给出所有物理成员的长度与 SHA。容器内 MANIFEST.json 对每个源成员记录原本地路径与取得类别；完整复核为 qualified_replay/QUALIFIED_FULL_EVIDENCE_REVIEW.json。所有 Git blob 不大于 350,000 B，没有新增可执行 verifier、忽略规则或 allowlist。
