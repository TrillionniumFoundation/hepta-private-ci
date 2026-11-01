# formal_03 磁盘写入中断与恢复口径

原两工作进程训练启动器在 2026-11-01 18:34 UTC 附近写入收据时抛出 `OSError: [Errno 28] No space left on device`，进程退出码为 1。这不是科学验收结果。

截至中断后核验，13 个训练组同时具备完整 768 步轨迹、选定/最终模型哈希、完整训练与验证身份以及退出码 0 的 wait4 收据。其所有原始文件均受 SHA256 保护，不重写、不重复计费。其余 19 个组使用原冻结 campaign 在各自全新的工作目录中从相同种子重新训练；不把中断的 final.pt 当作选定模型，也不从不完整状态继续优化。

两个已有活动证据的未完整进程尝试——recall_s15137_value 和 recall_s15138_light——分别保留。其原 wait4 CPU 与退出状态不可恢复，记为 null / not_measured，不以 0 或后来同名成功进程的 CPU 替代。13 份已成功收据的归档副本也不重复加入总账。

原始收据目录及两个不完整模型目录被复制到 `attempts/train_02_enospc/original`，并由 `PRESERVATION.json` 记录逐文件字节数与 SHA256。恢复尝试在 `attempts/train_resume_001` 独立登记。新收据在落盘之前先完整输出并 flush，以保留后续写盘失败时可读取的 wait4 记录；成功结果经验证后才发布到 canonical fits。

恢复启动器最多两个工作进程。可见剩余空间低于 1 GiB 时暂停自身子进程组，恢复至 2 GiB 才继续；这个保护只能观察当前文件系统报告的空闲空间，不能证明已解决底层配额、overlay 层或其他 ENOSPC 原因。报错后曾观察到数 GiB 可用空间，不能据此否认先前 ENOSPC。根因仍未知。

清理范围只包含已与两个远端检查点逐文件核验一致的四个临时 staging / fresh_restore 副本，合计 168 文件、100,986,928 逻辑字节。canonical fits、原始收据、压缩分片、manifest 和验证证据保留。精确路径及核验身份见 `CHECKPOINT_DUPLICATE_CLEANUP_REVIEW.json` 和 `CHECKPOINT_DUPLICATE_CLEANUP_EXECUTION.json`。

全部 32 个注册组完成后，训练 TOTAL 会明确标为 `resumed_consolidated`，`original_launcher_completed=false`。CPU 为 32 个选入成功进程的 wait4 之和；丢失/失败尝试另外披露。墙钟为原 restart 登记至最终补齐的含中断跨度，不宣称为单次启动器的连续运行时长。运行助手、复制、验证等 CPU 不混入工作进程费用。

本次恢复不改动主实验 36 个冻结源文件，也不改动已登记的 full_online_confirmation 与 train_execution_cross 源文件、条件或数据。所有确认步骤仍等待完整训练结束。报告与运行总账增加恢复语义只属于记账及执行修复，不构成选择更有利结果的重新登记。
