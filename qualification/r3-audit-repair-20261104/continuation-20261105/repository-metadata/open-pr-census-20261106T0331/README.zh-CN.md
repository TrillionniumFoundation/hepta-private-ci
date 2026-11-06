# 当前开放 PR 元数据普查：2026-11-06 03:31–03:35 UTC

本包记录 `TrillionniumFoundation/hepta-private-ci` 的直接 REST 开放 PR 分页。主遍历实际取得 **3,555 个不同 PR：3,506 Draft、49 非 Draft**。其中 **360 个以 main 为 base，3,195 个使用其它 base，共 2,220 个不同 base ref**；3,555 个 head 均来自同仓，跨仓和 head 仓库缺失均为 0。

## 来源与分页边界

固定请求为 `GET /repos/TrillionniumFoundation/hepta-private-ci/pulls?state=open&sort=created&direction=asc&per_page=100&page=N`。主遍历从 03:31:39 到 03:34:36 UTC，连续第 1–36 页：前 35 页各 100 条，第 36 页 55 条。03:35:08–03:35:10 UTC 完整重读首/末页并取得第 37 页实际空数组。合计 39 次完整原始工具返回，无 transport 错误、没有降页长，没有使用搜索。

39 个 `original/*.tool-return.json` 保存完整 MCP 对象的 UTF-8 JSON 序列化。其 `structuredContent.content` 是完整交付的 REST JSON 文本，两个内嵌副本逐份相等；这不是 HTTP wire/header 抓包。首次显示时不慎重复打印了嵌套正文并被显示层截断，完整对象在显示前已保存，归档原件不受影响。前 8 页另有在 code-mode 对原字符串计算的完整 Git/SHA256/字节数，与落盘原件逐份相等。其余所有文件均有完整落盘字节身份及归档校验。

主遍历无重复 PR、无 created 升序逆序；首/末锚的成员和次序均不变。末锚 **#4907 的 head、merge_commit_sha 和 updated_at 发生变化**，两份完整原件分别保留。首末锚不能排除未被观察的中间页并发变化；本包不声称原子快照或任何时间点绝对无遗漏。统计按主遍历首次观察计数，末锚不覆盖第一次原值。

## 与旧库存的关系

此前报告的 1,103 PR 是旧历史观察，本包不把 3,555−1,103 解释为新增或自然增长。当前 3,555 条中仅 88 条创建于旧上界 2026-11-05 03:24 UTC 之后，3,461 条的 updated_at 仍早于或等于该上界。旧参数、分页和数量差异的原因由独立旧来源补审处理，本包不猜测。**本次未重新扫描 branches；5,193 只能作为旧分支计数。**

## 重放

`original-manifest.json` 逐份固定 39 原响应及 `collection.json`。运行：

```sh
python verify_census.py --root /path/to/restored/root
python verify_census.py --root /path/to/restored/root --inventory
```

首命令重新解析全部原件、重算分页、计数、完整 base 分布、创建/更新日期分布及锚点差异，stdout 应与 `VERIFICATION.json` 完全相等；第二个命令 stdout 应与 `PR_INVENTORY.json` 完全相等。两个命令均只读本地材料，不访问网络，也不执行项目测试。归档恢复和异目录重放回执在外层 delivery 包中。

## 资格边界

这是完整已取分页的**元数据普查**。PR 正文中的作者数字不是本轮接受，不声称逐行审阅 3,555 PR 的源码、完整测试、required CI 或产品效果。本次没有查询新的 CI/native，没有修改 PR/ref，也没有 dispatch、重试或取消任何任务。原 23 项退出条件、canonical 模块范围和既有产品资格不由该人口统计改变。

## 随包旧库存摘要窄补审

OLD_SUMMARY_REVIEW.json 和归档内 old-summary-review/ 完整保存 actual 5fac62f 的全文 GET、原摘要及对照。旧摘要声明同样 state=open、created asc、每页100，11×100+3+0；1103条全部在当前3555中。未见额外查询 filter，也未重开其旧原始分页归档，所以差异原因仍 UNKNOWN。此附录追加于新普查 core 冻结之后，没有改写新39原件或首次统计。

完整压缩归档可由 restore_bundle.py --output /empty/destination 恢复。bundle-manifest.json 固定每个分片及所有成员的字节数、Git身份和SHA256。offline-replay-receipt.json 保存独立目录的实际恢复与三次只读统计输出逐字节相等结果。实际Git create/full GET依据在 registry.actual.json。
