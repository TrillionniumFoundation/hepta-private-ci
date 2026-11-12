# 原始终态证据与最新增量

截至2026-11-12 18:52:55 UTC，源码Draft PR6213已发布872b1b68342285893abd4c09f9141bcc19d8f9ce / tree5a22d17b8d21f2b9843d508ec4ef21f8045a0c66：46路径修复已静态复核。准确head在18:35:16的Actions集合total_count=0，尚无该版本执行PASS。实际base已到d3977d9a1bed3e89952c576c45660b04ea674faf，31个重叠文件和5个必要retention接口适配正在整合。

原edaf与286c各完成1,738普通方法：1,730PASS、7FAIL、1TIMEOUT、98过滤、0重试；Root和maintenance未到达。两版各自caller真实success（541边界／541清单／390保护／6,604Rust文件），authorityGranted=false。edaf Windows私有状态专项36/36成功。edaf GNU／musl超时及Windows／macOS／Fence失败均保留，不转为当前source结果。

本次先独立核验144个不可变条目：133个资格证据文件与11个只核对而不导入的源码后像；重新拼接8份完整日志，所有原字节数、SHA256与Git blob一致。另新封edaf caller完整2,150,402B原日志，7连续分片、原timestamp/BOM receipt与job元数据。此前已核其他平台原job的独立直接读取也保持准确source。未另取的完整XML／ZIP／inventory仍不计已取得。

[872b源码审查](../../../evaluated-current-read-20261112/repair-872b-review/ROOT_SOURCE_REVIEW.json) · [三方整合](../../../evaluated-current-read-20261112/merge-d397-review/ORIGINAL_THREE_WAY_OVERLAP.json) · [完整字节核验](ROOT_IMPORTED_BYTE_READBACK.json) · [edaf caller](../../../evaluated-current-read-20261112/edaf-caller-success/MANIFEST.json) · [blocker清单](../../BLOCKER_CLOSURE_NEXT.md) · [机器索引](../../TERMINAL_EVIDENCE.json)。

完整研究资格仍12门OPEN，owner_decision=null，HOLD，all_blockers_closed=false。原研究NoUpdate、失败、UNKNOWN与冻结四次B/C结果不改写。无actor重派、PR合并、部署或默认采用。

## 历史原说明

[f409 README](../history-20261112/TERMINAL_README-f409.md)、[f409完整索引](../history-20261112/TERMINAL_EVIDENCE-f409.json)与更早快照按原字节保留；其中“进行中／未推送／当前”属于各自当时观察。本页以上与机器索引是新状态。

[本次发布树与字节独立核验](GIT_READBACK_EDAF_TERMINAL.json)：暂存提交161个变更路径均限于qualification，32个Git树节点及10份新文本完整字节已读回匹配。最终提交另加入该核验记录并更新索引；不代表新source测试通过。
