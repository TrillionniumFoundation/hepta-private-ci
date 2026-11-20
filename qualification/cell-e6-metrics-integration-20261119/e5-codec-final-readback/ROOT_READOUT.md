# E5 codec 最终发布回读

最终 Draft #6790 为 `148e37c26586677e83f0e57e100def8805c1a020`，tree `def1b4b5f6fcdb8be50afb89224e0407a0763ab9`。从原材料 `63f494553a735bd55a3fef7cfe2e76604cd6db7d` 到最终 head 的完整 58 个差异路径，实际通过未修改的 512,000 字节原门，exit 0，用时 0.57374746 秒。最终门 RESULT SHA256 为 `cb29b086bf102f1b5fd9a5099b439c9aad7eb6d577f619cdf8e1a757b40416b9`。

归档保留原 owner、stdout、stderr、退出记录与完整路径核验；全部成员已经解包逐字比对。它没有被再次写入受测 head，作为本联合 checkpoint 的独立回读证据，避免递归改动受测身份。根在 CAS 后另外新鲜读取 #6790，确认该 head 仍为 open Draft、unmerged。

16/16 完整结构 roundtrip，11/16 可见动作 roundtrip；原 1／4／16 prefix 均不具备本实现下的表示准入。唯一满足全部原表示上限的 attrs 仍在零基 ordinal 11，没有重排。当前训练准入 0，新增模型加载、forward、generation、训练和上游 native 重放全部为 0；这不是学习收益。
