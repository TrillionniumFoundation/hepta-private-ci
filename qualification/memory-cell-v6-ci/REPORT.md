# Cell V6 CI 复核

本次跟进只修改拼写检查的非冻结配置，原 `qualification/memory-cell-v6/` 的 301 个文件全部保持不变。训练、开发、独立留出和结构实验没有重跑或调参。

## 精确差分

对 CI 报错的全部 30 个文件，按提交 `984baab7ad5ceebaf97f11d6c60c928d3b69f1b1` 获取并核验 Git blob；使用官方 Codespell v2.4.3 源码与字典。原配置重现 384 条，更新配置后为 219 条，与基线输出逐条多重计数一致。移除本次 V6 新增的 165 条，旧项变化为 0。两个退出码均为 65；这不是全仓通过声明。原始输出在相邻 JSONL 文件中，文件指纹及限定范围见 VALIDATION.json。

仅跳过 V6 已序列化的模型、压缩块和源码快照的英文拼写扫描；另以七条原始正则行的精确匹配保留词干。没有把整个源码或文档目录加入跳过列表，也没有增加全局忽略词。

## 既有 CI 状态

[本次综合 CI](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/40578167818) 与 [基线综合 CI](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/40470653139) 均失败。已比对为同一原因的项：历史证据中的旧工作流引用检查；macOS 的 Fleet 测试辅助代码 Clippy 错误。Windows 的其他失败发生在本次 V6 目录之外，未在本机重现；不能笼统宣称无影响。依赖检查失败的详细日志未取得，原因保持未知。

这些 CI 失败不改变冻结研究结果：语义入口未达到门槛，同信息静态结构达到相同正确率且成本更低，自适应结构未证明独立收益。
