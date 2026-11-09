# 四项历史 CI 原件的安全重封版

范围仅原来已请求的四个 job。S deny 与 H deny 的下载因 180 秒上限中断，保留完整已收到 bytes，但完整性为 unknown；不能从这两份部分日志推出完整安全检查结果。H format 与 source-head UI 日志完整。实际 checkout 取原日志中的 git log 响应，并单独保存提交对象的只读回执；workflow head 元数据不代替 checkout。

此包从固定 SHA 的原始私有归档按精确 58 文件白名单读取，不把旧归档嵌套打包，不在磁盘解压。排除旧 seal001/viewer.* 四文件，包括完整 /user 资料；只保留最初已经 --jq 缩减为 ProfHepta 的身份回执。没有用户主机全量 inventory，没有 token/env 导出。原始 CI 日志可含托管 runner 的一般构建能力信息。

所有保留原件的内容、大小、SHA 与旧 manifest 逐项核对；各 stdout/stderr 未编辑。原 collector 的失败权威终态也保留。此操作没有重新抓取 GitHub 日志、运行 CI、测试或写 GitHub。

先前 44de5d… / 1,920,113 B 的安全包在当前不可读的 cloud 环境。本包是从相同原件新建的独立重封版，有自己的 SHA；不声称与它字节相等。失败、部分传输及其成本不因重封而消失。这里只支持历史诊断，不计入 M6 共同测试分母、科学收益或生产采用。
