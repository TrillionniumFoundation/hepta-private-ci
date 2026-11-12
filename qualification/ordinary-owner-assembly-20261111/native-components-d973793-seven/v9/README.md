# V34 原始原生运行：组件验收未通过

受测源码固定为 `d9737937eaccccf2ed2f1f79444ddec6c10d0eea`，tree `2402c0f7605c1e6d23430c5aaeea8d08743cac59`。原始七包 / 精确 Root17 完整入口自然退出 1；普通组件测试 1,950/1,950 通过，Root 16/17 通过。九项清理通过，源码和外部工具前后不变。没有重试、豁免、checker 修改或继承旧源码 PASS。

唯一失败是 Initial 首次 Publish 的 `verify_retained_use` 返回 `Unavailable`；本轮未进入 Recover。完整 Root launch 和 progress 原始字节已经按固定文件版本分块取回并验算；具体内部拒绝叶因尚未建立。publication broker 本轮通过不代表独立普通业务采用。

普通完整链 / 正向采用链 / NoUpdate 与 rollback 链仍为 **0/0/0**；独立 C 与 daemon + Root 真正 OS 重启仍未验收。系统错误没有计为 NoUpdate。同会话 phase 草稿不在这个受测源码中。

## 证据范围

`RESULT.json` 区分原入口报告、独立读取的原文件和仍待取回的文件。`progress.json`、`root.launch.log`、原 execution / UID / helper / JUnit 收集器记录以及完整 PTY 字节在此保存。纳秒时间的派生数值使用精确十进制字符串；原日志文本未经改写。

附加文件读取发生三次 MCP 超时，全部请求及工具原返回均保存在 `raw/`。原始 Root JUnit 本体、普通测试和 full-caller 的完整 stdout、完整压缩归档尚未取回；不能把引用的 hash 宣称成独立全量读取。旧 V12/V13 归档属于各自历史失败源码，不替代本次证据。
