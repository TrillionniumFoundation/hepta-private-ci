# 第三轮执行证据

`validation.json` 汇总实际命令和状态；`evidence-index.json` 列出每个原始成员的字节数与 SHA256。

`raw-evidence.tar.gz` 保留原始日志、原执行收据、源码前后清单、运行脚本、工具链清单、环境暂停和失败尝试，以及旧 head 的 hosted CI 日志。解压后目录为 `host/`、`ci/` 和 `control-review/`；成员的原始字节已逐个重新读取并验证。

原始收据没有记录 Git HEAD 的阶段明确保留该缺项；控制临时文件造成的 delta、机械 fixer delta 与真正代码失败分别记录。结果不构成默认完整循环、独立科学、目标宿主或部署接受。
