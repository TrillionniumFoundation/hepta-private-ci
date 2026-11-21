# 旧 E5 来源与 AST 排除证据

本包保存固定旧材料、恢复原响应、本地派生排除集合及尚未执行的同解释器复核准备。没有读取新候选仓库，也没有导入或执行旧材料代码、运行 native / 训练 / 实验。全部内容追加保存，不改变既有 E6 证据或任何分支历史。

## 固定原件

来源为 `hepta-private-ci@7f790fb2f907ef9e618c3c7d233d22135ab00580` 的 `qualification/cell-e5-material-adapter-20261120`。原 payload 保持 2995743 B，SHA-256 `73504304a1c6e220f085d91845f3b585b73bfb649dd829b38a06e62ee7e8c2f9`。八个原 part 的整文件 SHA 与 Git blob SHA-1、拼接整包 SHA、1645 个成员的 SHA/长度都经过核验，逐项匹配原 BOUND_INPUT_ROOT。成员合计 14013639 B，包括 MATERIAL_INDEX、16 份 material 和1628个内容寻址 blob。

46 个有效读取块覆盖原包，共 47 次读取。一次 `part-002.bin / offset 262144` 返回 MCP UNAVAILABLE / Connection failed，原响应完整保留。只补取同版本缺失范围；超出原响应的故障原因仍为 UNKNOWN。恢复没有启动 H 进程或实验。

## 派生覆盖与限制

| 覆盖 | 数量 |
| --- | ---: |
| 索引内材料 | 16 |
| 逻辑源文件记录 / 不同完整文件 SHA | 1331 / 1216 |
| 尝试解析 / 成功的 Python 内容 | 488 / 487 |
| 函数节点记录 / 不同函数 AST SHA | 9145 / 7116 |
| 声明原生测试文件的模块 AST | 17 |
| 指定原生测试函数 AST / 已发布原片段 SHA | 47 / 47 |
| 不同排除 owner / project / source_id | 各 17 |

整文件哈希直接来自完整原字节。函数哈希严格按 `hashlib.sha256(ast.dump(node, include_attributes=False).encode()).hexdigest()`，覆盖所有 FunctionDef / AsyncFunctionDef，包括方法与嵌套函数。没有删除装饰器、归一化空字段或改写 type_params。模块、函数和每个原 material 的引用都保留独立索引。47 个指定测试函数的原字节片段与旧 SHA 完全一致，并在完整文件 AST 中各定位到一个节点。

本次实际使用 Python 3.12.14。唯一解析失败是 `Delgan/loguru` 的 `tests/exceptions/source/modern/t_string.py`，第 11 行 SyntaxError；347 B，SHA `41eed63ebe554f293ef0176b3cedaf4f01b8c9b8307f66ad43640b944367f221`。原 SHA、owner / source 排除与失败记录全部保留，AST 完整覆盖标志为 false；不把该文件静默丢弃或改写后冒充原件。17 个声明原生测试文件及 47 个指定函数均成功解析和定位。

16 份 material 及其 240 个旧 JSON 元数据中未见已有的 AST / fingerprint 命名字段；该零结果显式保留。既存的完整源文件 SHA、原生测试文件 SHA 和 47 个原片段 SHA 仍完整保留；新 AST 全部标为本次派生。

## 未进入材料包的旧曝光也排除

原 payload 中的 selection audit 原件为 `blobs/8e1a2edba1e4394f57494a2035ec1d35116e6a2fcd74ad5dfd8cf34e5d42a6d9`，30027 B。它的11个 selected 项包含 `github:agronholm/exceptiongroup:pull:155`，before `2cba84352c3f01e8af2f37bf102d0dd515e15dc0`、after `0c6cfbf677f6b50df17311cfdad01e9ff17310aa`。

该来源不在16份 MATERIAL_INDEX 中，因此没有为它虚构源码或 AST。但其旧曝光已经足以列入 owner / project / source_id 排除，所以排除源数为17，材料数仍为16。缺少 AST 不代表新来源。完整旧 inspected/skipped 曝光和其他历史任务仍须与 root / E2 的排除集合合并。

## 同解释器复核准备

后续 fresh 宿主使用已合格的 desktop Python 3.12.3：`/usr/bin/python3.12`，8020928 B，SHA `e50d468e8b0adfb05733f5b87b3cff34829c4a8c1aea50c865aa8bdfe4bb150f`。既有 C owner / CPU PLAN 和实际 H launch 原件都已保存，host 没有从 ROG 推断。

本包保留当前派生器及另建的 qualified_v2。后者的完整 payload/material/指纹派生代码与已运行 v1 逐字相同，仅新增实际 `/proc/self/exe` 路径、长度、完整 SHA、稳定 FD / 当前同名路径检查和60秒期限。复核计划用新的 inputs / derived 目录、`-I -S -B`、90秒 H 上限和固定单次 key，由 root 决定并启动；没有导入训练包或修改 C。

**同解释器复核尚未执行，本包不宣称 Python 3.12.14 与 3.12.3 的 AST 字节已经等价。** 两份结果应原样比较；任何差异保留，不能通过删字段等归一化来制造相同结论。既有本地派生结果、v1 和最初的未绑定计划都作为历史准备稿保留。

## 容器与索引

`CONTAINERS.tsv` 是两容器的长度、SHA与分片顺序；`CHUNKS.tsv` 保存每片偏移、长度与 SHA；`INDEXES.json` 定位完整1645成员 BOUND_INPUT_ROOT、16材料 MATERIAL_INDEX、sidecar逐成员清单、EXCLUSION_E5、FINGERPRINT_SETS 和 qualified_v2计划。新 sidecar 同时保存所有原恢复响应、固定Git读取回执、派生明细和解析失败列表。没有重复打包原 payload 展开目录或重建的 chunk / part 副本。

每片为实际二进制且不超过350000 B。按文件名顺序拼接到新路径，再先核整包SHA：

```sh
cat payloads/old-e5-original/part-*.bin > /tmp/hepta-old-e5-payload.tar.gz
sha256sum /tmp/hepta-old-e5-payload.tar.gz
cat payloads/old-e5-exclusion-sidecar/part-*.bin > /tmp/hepta-old-e5-exclusion-sidecar.tar.gz
sha256sum /tmp/hepta-old-e5-exclusion-sidecar.tar.gz
```

若临时路径已有内容，应使用新的路径。解包前按索引核验成员并拒绝绝对路径、父目录跳转或链接。包中脚本是冻结的离线准备原件，没有自动执行门禁、allowlist 或 ignore 变更。

文件、函数和测试计数只衡量排除覆盖，不新增独立科学样本。精确哈希不能穷尽改名、编辑或语义克隆，owner/source 排除及严格的未来任务设计仍需保留。
