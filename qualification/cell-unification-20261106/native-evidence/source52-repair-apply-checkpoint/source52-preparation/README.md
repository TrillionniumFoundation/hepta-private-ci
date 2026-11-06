# Source52 单叶离线登记准备

基线是实际 source51 commit e28b0f385ee882f842911044958b2810f62f6379 / tree 763c8d2b4089f6e9806c3bbb68fa247bc2f6af36。本目录只从四层固定 GitData 非递归树原件离线重算，未创建 Git 对象、commit、分支，也未改动 native 或运行 Rust。

唯一变化为 runtime.rs 的四个域名策略 fixture 初始配置；原断言与生产代码保持。完整 candidate、原文、2255B patch 及独立审查固定在本组。预计新 root tree 为 211f15baff19095e8c98bcea2b0ed99ca2270ade，该值仍是离线预测，source_commit=null。

runtime.rs 已是 source51 仓库的真实叶节点，但不在相对 framework 的194条变更清单内。因此新清单为195条＝181 Rust＋14其他。原194条对象的字段和值，以及每条对象内部 JSON 原字节均验证保持；owner仍26、CI选择项仍27，没有依赖或双锁修改。未来仍需 actual metadata 与原门验证。

主要文件：
- PLAN.json：未执行的登记／后续五成员 apply 输入契约。
- candidate-source-manifest.json：195条 provisional 清单；commit未创建。
- source52-delta-manifest.json、candidate.patch：唯一叶的变更与原补丁。
- input/original-trees/：四份实际 source51 GitData 内容字符串原件。
- derived-trees/：只替换一个叶及其祖先引用的四棵预测树。
- ROW-PRESERVATION.json：原194条 JSON 对象原字节逐项 pins。
- TREE-AND-PATCH-READBACK.json：四树原hash、三层父子链接、单叶以及补丁正逆复算。
- input/candidate-independent-review.json：冻结候选的独立静态审查，未执行Rust。

root须在实际创建source52 commit后重绑actual manifest与delta，并生成最终五成员输入包；本组没有创建可运行native输入归档。原r26 FAIL保持，科学HOLD、DENY_ALL不变。
