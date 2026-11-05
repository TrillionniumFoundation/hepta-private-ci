# 下一产品 head 的原 CI 收集计划

## 绑定与启用条件

这是只读收集计划。代码候选为 `5b6331250ff459033bd44d1a95daec70131277cc`，代码树为 `b26598d0d97d8d51e723bb5582137315f2174d35`。它们目前只作准备锚点；真正 published head、最终树及各合成 merge 均留空，等发布负责人确认后再从原 API 和原 checkout 核实。最终证据提交可能改变整树，不能拿代码树直接替代发布树。

产品旧 head `0e139b599f0fe451f80fb7db4b2913bb9c679dce` 的查询已暂停。旧矩阵已有多次取消，现存证据没有确认 actor 或原因；新发布后的取消将按新的观察时刻单独记录，不能仅凭时间相邻认定因果。本计划不会 dispatch、重跑、取消任务或改任何 ref、测试、预算与筛选。

## 原范围

工作流表记录原 **19 条 workflow** 及它们的复用 workflow、真实 job 条件、原预算和 artifact 合同。这是历史原范围，未来是否触发仍以新事件实际 API 为准。具名退出表保留 **142 个不同 `(binary, name)`**：

| 原 ID | 具名数 | 精度要求 |
|---|---:|---|
| B07 | 28 | Core22 与 MCP6；Windows 原 cfg 排除及原 ignore 分列 |
| B08 | 4 | 已核两 recorder、一个 wire、一个 replay；不补造第三 recorder |
| B09 | 19 | Core unit/集成、AppServer、普通与 Wine 变体分开 |
| B10 | 14 | 十个原失败及四个 turn-state；保留已更正的真实 prewarm/request oracle |
| B13 | 9 | Queue8 加 Agentd cognitive-write-qualification1，不能用普通 Agentd 总数补第九例 |
| B20 | 19 | HTTP/WebSocket/EOF 原19例与各 attempt |
| B21 | 31 | 原 Intel30，加独立 collector control1；Linux 窄测不替代 Intel |
| B22 | 13 | 需要 TUI 原用例成功正文；目标 PASS 不能补齐缺失正文 |
| B23 | 5 | Unix signal3 与 portable drain2；Windows 只适用后两项 |

另列 strict Windows8、exec resume13、两私有目录原例、Core cold-root/Proxy、CodeMode审批，以及历史25个早返观察名。这些是补充观察集合，不混入142的分母，也不要求重跑已经具备证据的历史冻结反事实。

## 优先回收

| 原门 | 新 head 必须留下的事实 | 不能替代它的证据 |
|---|---|---|
| Mac wrapper57 | 原57的实际 macOS Bash 结果、完整失败/成功名、实际脚本身份与退出码 | Linux/Windows57、仅语法检查 |
| Intel PTY | 原30与新1分列；drain原2秒/4MiB/exit0、完整 attempt 及诊断观察 | Linux29或诊断已编译 |
| 真实 musl产品 | 正确 canonical platform、Rust/C/rustlib musl、实际 CLI build、静态 ELF/hash、运行该二进制的 version/help | 同 GNU/RBE 的 musl 标签、解析器接受两条相同 label |
| V8 staged smoke | 每个实际 native 行的六个原 case、artifact/binding/feature/target 身份 | 四个 cross-musl 行原 smoke skip，或只有资产上传 |
| Windows strict/helper/TUI | 原3严格例与新5控制、host负控及物理拒绝；同 target helper前置；TUI13正文 | 总目标数、仅失败目标 archive、Linux 的 cfg 无执行 |
| Core integration | 原普通与 Wine 目标分别回收全部 shard/attempt；CodeMode与cold-root精确正文 | Windows Core2343单位测试总数 |
| Proxy | 非 Windows 原 CONNECT与2秒响应行为；Windows原 cleanup/early-return分列 | Windows同名PASS |
| B13第九例 | `hepta-agentd-cognitive-write-qualification-test` 中原H7名字的正文 | Queue8、普通Agentd库、operator fixture总数 |
| UI browser | 实际浏览器/renderer运行、source与browser-merge分别绑定、完整HTTP/product结果 | 构建/工具安装/摘要、空manifest、native-presentation或SDK诊断 |
| Codespell / fmt | 新实际源码原配置和原工具的完整退出/差异 | 静态候选审查或旧源绿色 |

“V8六smokes”在这里指六个原测试名。原配置有12个矩阵行，其中8个可运行 native Cargo smoke，4个cross-musl行明确跳过；不能把行数与用例数混算。条件式 Windows source/link 资格也单列。

## 回收与判定规则

发布确认后，先固定 PR/head/base/main、原run及run_attempt，再完整分页 jobs。实际 source、普通merge、UI browser merge、native-presentation merge各自记录父链和整树；同树不合并 provenance。

对终态或已经出现失败的任务保存完整原日志。小结果工件校验API给出的size/digest、ZIP CRC与每成员hash，随后按 `(binary/name/target/platform/run/attempt/shard/test-attempt)` 投影。已有的成功日志保留器含11个目标；它报告缓存、未报告、缺失文件时如实保留，不能凭文件mtime或旧目录补资格。XML的普通失败、timeout、leak、ignored、retry与正文早返分别保存；只规范化原libtest明确的 ` - should panic` 显示后缀。

历史25早返只作检索基线。若新原日志仍明确提前返回，即使API、目标或JUnit为PASS，也记录为行为未执行。反过来没有完整正文时，不猜已执行或仍早返。原取消前真实FAIL与实际PASS都保留，取消不会擦除它们。

收齐一批便冻结不可变原件及摘要，后续另增批次，不改旧观察。当前原23台账仍是 **8项范围闭合、14项OPEN、B18科学HOLD**；本计划不修改任一原退出条件，也不把单项CI绿灯扩成整产品或真实外部接受。

## 机器清单

- [collection-plan.json](collection-plan.json)：启用条件、身份字段、回收顺序及判定范围。
- [original-workflows.json](original-workflows.json)：19条原workflow与复用job/预算/artifact合同。
- [named-exit-cases.json](named-exit-cases.json)：142个具名映射、补充集合、原cfg与旧早返观察表。

以上文件仅在本目录创建；没有修改产品源、台账、共享registry或CI。
