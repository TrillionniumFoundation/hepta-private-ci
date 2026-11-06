# V9 postcut 实际审计追加发布：独立验证包

实际发布提交为 `46fd74d98c1cef42e1439920f9ca83361481b3d8`，父提交为 `089c13ab39cedb9fea0f9e9bd03d95317936cd65`，实际树为 `41d583262bc6ccd794ffb9e8e9ac9d04665ca85d`。离线核对确认：**205 个新增路径，204 个登记项加索引；原有源码与历史证据没有覆盖或删除。** 原 23 项状态保持 15 CLOSED_SCOPED / 7 OPEN / 1 SCIENTIFIC_HOLD，不能据此宣称所有 blocker 闭合或整个产品资格通过。

`root/` 保存根指定的 10 份实际 postcut 原件、完整 prior089 树、prior089 实际提交回执，以及两份此前完整 PR body 原件，共 14 文件。`verify_postcut_publication.py` 只读取这些保存字节，独立计算完整 Merkle 树、增量阶段、索引映射、提交/ref 身份及完整 PR 历史；不联网、不重取 204 个 payload、不编译、不执行 native 或修改 ref。

## 已核对的事实

| 项目 | 独立结果 |
| --- | --- |
| 原始树 | `cd5ad6773d53055ae79cf3a5b79703406161eb69`，12,917 叶子、2,049 目录节点；绑定 prior089 实际提交 |
| 追加后树 | `41d583262bc6ccd794ffb9e8e9ac9d04665ca85d`，13,122 叶子、2,092 目录节点；绑定实际 root GET 与提交 |
| 完整差异 | 恰 205 个新路径，全部位于原 continuation 证据前缀；0 修改旧叶子、0 删除 |
| 索引 | 实际 blob `73365de8c684e33fbdb8f994b44ac4834ed92170`，168,133 字节；本地原件 hash、登记回执与实际树 leaf 相同 |
| 登记项含义 | 204 个路径登记项对应 180 个不同 blob 哈希；相同内容可以出现在不同证据路径。没有把它们描述为 204 个不同 blob |
| 增量构树 | 40 / 40 / 40 / 40 / 40 / 5 项共六阶段，逐阶段重算结果与实际 create_tree 返回 SHA 一致 |
| 引用与提交 | before ref=089，after ref=46fd；实际 commit 仅有 parent089，tree=41d583 |
| PR #4797 | 保存切点 head67；完整记录 body 一致，并完整保留此前 49,910 字符 body 作为后缀 |
| PR #4884 | 保存切点 head298；完整记录 body 一致，并完整保留此前 24,510 字符 body 作为后缀 |

204 个已登记项的完整 hash/字节数与 actual full GET 标志沿用冻结索引，本次没有重新给底层产品、测试或数据资格。所有新增路径与该 204 项加索引的集合严格相等。PR 中指向本次 46fd 提交的文件链接均在该实际树存在。冻结索引的主产品仍为 67cc/3982，B11 诊断仍为该切点的 2980/9cb；后续 v3 发布属于另一份证据，不能覆盖或倒写这个历史切点。

Linux67 包仍为 disabled preparation：execute=false、guard=null，原盘门槛 64,000,000,000 字节、RAM 34,359,738,368 字节、jobs4。索引不提供新 host 容量证据，也不把准备包当作执行成功。

## 首次构树失败没有丢弃

根原件保存第一次 160 项 create_tree 的 422 timeout 摘要、当时 expected tree GET 404 原始结果和审计 ref 仍指向089的原始结果。随后六个较小阶段最终得到同一个预期完整树；第四阶段恰到达原先 160 项的目标 SHA。这与早先 404 发生在不同时点，不能抹去第一次失败。422 的原始完整错误不在这份根 JSON 中，根原件明确说它保存在工具 transcript；本包保留该范围，不补造原始 HTTP 回执。

## 使用与范围

在恢复目录运行：

```text
python verify_postcut_publication.py --root root
```

完整 stdout 记录于 `verification.stdout.original.json`，stderr 为空。它列出全部 205 新路径、六个阶段、完整 PR body 的身份和范围。`snapshot-manifest.json` 对 14 份冻结输入逐一提供字节数、SHA256 和 Git blob 身份。编写 verifier 时曾误把 `link_checks.missing` 的空数组当作数字0，已仅修正 verifier；该开发失败留在 `preflight-001/`，未改变任何发布原件或产品断言。

归档包含所有验证依赖和原件，base64 分片均小于 480 kB。最终 actual registry 和独立 receipt 记录对象及清单自身的完整 GET 一致性，发布历史和所有旧 registry 始终不改。
