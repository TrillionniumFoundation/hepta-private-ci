# main67：2026-11-06 02:44 CI 增量原件

本包固定保存 9 份输入：5 份 GitHub API 原始 MCP 返回、3 份工具交付的完整 decoded job log，以及采集元数据。原日志以字节读取和保留，包含原 UTF-8 BOM；没有 newline 归一化。3 份日志的外层工具 wrapper 由根另存于 code-mode，不是本包成员，也不声称这里保存了 HTTP wire bytes。

## 有界状态

19 个完整 workflow runs 在 02:44:37 UTC 的状态为 10 success、2 queued、2 skipped、4 failure、1 in_progress。随后 02:45:56–02:45:57 只读取 4 个变更 run 的完整 jobs：23 jobs = 19 success、3 cancelled、1 in_progress、0 failure。此处不能重建或宣称新的全量 58 jobs 切点。三个日志读取时间为 02:53:23、02:53:27、02:53:29；观察不是原子快照。

四个顶层 failure 不是四个已证实产品失败。上述四 run 子集的三个取消属于 V8；本包不归因取消原因，也没有新取其他 run 的 jobs 或取消原始日志。

## 两条 UI 日志的确切范围

两条日志分别来自 base-merge 和 source-head。各自有 88 条实际 nextest PASS；另外四组 gateway 为 9/5/12/2 PASS，明确保留 31/35/28/38 filtered/skipped。各自 10 组 Node TAP 的 tests/pass 为 13、5、159、12、7、32、1、4、31、41，各组 fail/cancelled/skipped/todo 均为零；另有 libtest 5 PASS，以及 browser 四组 6/7/9/1 PASS。不同命令、lane 和范围不能合计为 unique 或独立试验数量。

每条 UI 日志均有四份完整 gateway JSON，共八份。它们绑定原 source 67cc5c28、base 63652be6、实际 source-head 67cc5c28 或本地两父合成 merge c0f9b518，全部 before/after 同一 3982ba56 tree、clean、exit/command/returncode=0、无 timeout/output limit。完整记录及前一行原 nextest 摘要和逐名 PASS 均由 verifier 核对。JSON 中对每个内部 log 的摘要字段原样保留；本包没有另取或重建这些内部 artifact 文件，不把该字段称作独立 hash 回读。

SyntaxError 属于明确的 malformed-JavaScript 负控；后续实际 TAP 行为“ok 25 - rejects malformed JavaScript without modifying the pristine bridge”，该组最终 32 PASS/0 FAIL，不能将这条预期诊断计为新失败。

## Objective 控制台边界

Objective job 127581904963 的完整 decoded console 和 success API 状态已保留。控制台包含 12 个实际 original gate 开始标记，嵌入脚本将内层 stdout/stderr 写往独立 artifact 文件，控制台没有原 nextest/libtest 结果摘要。本包的 Objective case count 明确为 null；52 成员完整 artifact 由另一份包验收，不能从打印的脚本或 API 绿色自造逐例数量。

## 离线恢复与复核

从实际登记文件取得 bundle-manifest.json、restore_bundle.py 和 parts/ 全部文件后运行：

```bash
python3 restore_bundle.py --bundle . --output ./restored
python3 restored/root/verify_cut.py
```

恢复器首先核完整分片字节、Git blob、SHA256、解码分片和完整 gzip，再逐成员校验原始字节，不接受 link 或路径越界。verify_cut.py 只读本包原件，不调用网络或产品；其 stdout 应逐字节等于 root/VERIFICATION.json。README、verifier 和完整 VERIFICATION 也以直接 Git 对象登记方便查看。

review-history/ 保留离线解析器两次初始边界错误：UTF-8 BOM 和 GitHub 多行 path 字段不重复时间戳。最终解析器保留原件、只在派生解析层识别这些格式；这些是审阅工具开发过程，不是新产品或 CI 失败。

本包不关闭任何 blocker，不证明主候选全部 required checks 通过，不进行 dispatch、retry、cancel、native 或 ref/PR 写入。

