# 恢复后重新核验

这是 r21 原始 checkpoint 恢复后的新读回，不是旧正式附件组的逐字恢复。

archive、INDEX、evidence 和 input 均来自按原 SHA 恢复的归档。大 UTF-8 文件采用 mtime=0 的 gzip；映射保留压缩前后 SHA，并逐项验证解压后等于原字节。完整源码留在原 archive 中，不另复制 source 目录。

本次只运行 Python 读回，没有重跑 Rust、改写原件或读取后续活动日志。唯一测试 ID、退出码、资源、outer terminal 和 source guards 分别核对。原阶段数值不转移为其他源码资格。

RECOVERY-READBACK.json 中旧组 pin 仅为历史记录，不表示旧报告字节已恢复。独立原树重建由另一个新审计补充；最终附件清单待 handoff 后封存。
