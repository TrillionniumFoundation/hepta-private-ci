# E2 首个真实来源：扫描与四次原始材料尝试

本包记录固定来源 `tartley/colorama`（repository index 0）的完整实际过程：**扫描成功，四个原定 material 按顺序实际尝试，全部在兼容性阶段 REFUSED，贡献 0 个通过原生验证的新任务。** 四次尝试的模型调用、native qualification 调用均为 0。拒绝发生在模型执行前，因此不能据此评价学生表现或训练收益。

## 实际顺序与结果

| 阶段 | 原位置 | 实际 H job | 终态 | 共享 Git 槽位 |
|---|---|---|---|---|
| 扫描 | repository 0 | `1a1fdf0dc8b-ffbe-2021` | succeeded / 0 | 0000–0185 |
| material 00 | [4, 2] | `1a1fdf8e0e8-ffbe-2038` | failed / 1；FINAL REFUSED | 0186–0189 |
| material 01 | [17, 0] | `1a1fe02ce8c-ffbe-204a` | failed / 1；FINAL REFUSED | 0190–0193 |
| material 02 | [31, 0] | `1a1fe071e57-ffbe-2054` | failed / 1；FINAL REFUSED | 0194–0197 |
| material 03 | [33, 0] | `1a1fe0b9f9a-ffbe-205d` | failed / 1；FINAL REFUSED | 0198–0201 |

四次原始 FINAL 都保留 `ValueError: exactly one original supported test root required`。实际 Git tree 原件含 `colorama/tests/` 的嵌套测试路径，而固定规则要求根目录存在且只存在一个受支持的 `tests` / `test` / `testing` / `test_suite`。没有为通过该规则而改源、搬运测试、过滤测试、加依赖或跳过原顺序。

material 00 首次 H start 返回 MCP timeout。原错误、相同参数与 key 的 reconciliation、`reused=true`、`retried_launch=false`、相同实际 job 和唯一 material claim 都保留。这是一个已启动任务的身份核对，实际材料尝试仍为一次。其余三个 ordinal 各有独立的唯一实际 job。

## 扫描原件与材料原件

扫描原 RESULT 为 16,700 字节，SHA256 `7f57561507007684121b7d783a83806b8f37b1752b6fda9130ba23c81ecd1434`。固定协议保留 50 个 commit ID，实际检查前 34 个 commit，按规则在首四个 potential 处停止，余下 16 个未读。19 个 source row、38 个源文件 blob 和全部 186 个 Git 命令的原回执完整保存。

扫描预期证据共 **1,061 份原文件、414,429 字节**。每份都重新与原始 H tool response 的路径、完整 UTF-8 或 binary 字节、version 和 SHA 对应；38 个源码 blob 同时核对 Git blob SHA1，186 个命令核对原 argv、共享槽位、exit 0 和完整 stdout/stderr。

每个 material 保存 23 份 owner 原件，包括 ATTEMPT、FINAL、material claim、四个 Git 命令的 INTENT / STDOUT / STDERR / EXIT 和四个共享 slot。四次合计 92 份原件、54,198 字节。扫描加材料合计 **1,153 份 owner 原件、468,627 字节**；这些文件数量、命令数量和 potential 数量都不能充当独立样本数。

每个 material 的 H 原 stdout 为 0、stderr 为 1,080 字节，均与完整原 bytes_hex 对应，H terminal 为 complete / durable / confirmed 且没有 timeout 或 cancellation。16 个 material Git 子命令全部 waited exit 0、error null、完整输出。原 uncertainty marker 和 before/after native claim 路径分别得到明确 FileNotFoundError，和 FINAL 的 native 上界 0 一致；没有据此推断无关宿主进程的状态。

## 预算、冻结与时间口径

该来源共消耗 202 个 Git 命令槽位，连续范围 0–201；原 repository cap 为 2,000，扫描和各材料共享同一槽位目录。每个 Git 命令原上限 600 秒；每次原 `GitCommands` 实例有自身 1,800 秒时钟。扫描 H 外层 1,860 秒，material H 外层 2,160 秒。包内没有重置槽位或放宽原预算。

选择已在 commit `4c55d9bfe1898c0066b3ae7cb05744fe99f6b418` 固定后才开始来源访问。`AS_OF=2026-11-21T03:00:00Z` 保持原值；冻结后访问不证明这些任务在学生训练之后才产生。现有恢复环境 checkpoint 为 `44864f0f2937b86d4696deaf5fb0835067d33a13`，不把它的发布时间冒称为首次来源访问的先决时刻。

原 DEPLOYMENT、scan 与 material 00–03 的准备 envelope、material 01 的两个措辞版本、五份与 DEPLOYMENT 全 SHA 相符的既有协议源码均保留。material 01 两版本的 H 参数字节相同。所有源码只作为原始文件读取，不被收证者导入或执行。保留实际运行产生的 AST 指纹，未用本地另一 Python 版本重算替代。

root 最终控制 freeze 绑定首来源目录的 23 个文件；`ROOT_FIRST_SOURCE_COMPLETION.json` 与四个实际终态、位置、review SHA 和槽位逐项一致。后续其他来源的元数据、任务或活跃目录没有读入本包。

## 原错误与证据范围

两次远端目录 listing 的 SSH 255 原错误保留；随后依据固定执行源码和实际 RESULT 构造预期证据清单，完成全部已知文件回读。该过程不等于远端目录的原子快照，也没有复制整个 `upstream.git` 对象数据库。H 的 durable 标记只支持对应 H 流，不能扩写为全部原 Git 文件的新增断电持久性保证。

首次准备时的本地 AST 常量组装错误、peer 回读时的数据路径说明、root 三次包装结构错误、收证者首次遗漏 `settled` 包装的本地解析 traceback 都保留。修正只涉及理解已保留的响应结构，没有重跑源扫描或改变原文件。material 03 的 `requests/results` 与其他材料的 `query/result` 两种原包装都按原样保存。

这一来源提供了真实接入、原顺序执行、预算计数和诚实拒绝的证据。它尚未提供通过 native 验证的独立新任务、学生失败恢复、能力保持、学习收益、真实用户增长或经济结算资格。模型与 native 调用为 0 仅描述本包首来源阶段，不覆盖项目中的其他独立阶段。物理能耗、网络字节和完整存储成本仍没有闭合计量。

## 归档与交接

`CONTAINERS.json` 描述一个本地新建 xz 容器；`CHUNKS.json` 给出按序连接的二进制分片、offset、长度、SHA256 和 Git blob SHA1。每个分片最多 350,000 字节。`MEMBER_INDEX.json` 位于容器内，列出全部源成员的长度、SHA 和分类；其自身由外层容器描述绑定。封包后每个成员均重新核对。

`SUMMARY.json` 给出汇总，三份 `INDEPENDENT_*_REVIEW.json` 提供纯本地重新核验，`REFERENCES.json` 指向已有选择及运行环境证据。没有重复打包旧 wheels 或完整旧排除归档。新增发布文件只有五份文本和二进制分片，均为 100644；没有新增 verifier、ignore、allowlist 或科学协议。immutable blob 交接后，实际 tree / commit / ref / PR 仍由 root 完成。
