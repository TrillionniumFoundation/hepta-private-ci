# #6240 完整原合约门：v4

固定源码：`2411261240f0f38bd0d60e2ba158304f918b8ce1`，tree `da633e55b6783b46f65a3e2c55d0ec753bd09c80`。
实际 job：`1a1cf734db5-2564-1a2c`；唯一 key：`neuro-ctrl6240-full-2411261-862531d11598-v4`。

## 已核结果

28 套原 workflow 合约测试，各自满足原 minimum；共 **200 passed / 0 failed / 0 skipped**。
保留原 `scripts/hepta_ci_exec.py`、每套 120 秒超时、原 `uv run --frozen … python -m unittest -v` 命令。
原格式检查及 E9/F63/F7/F82 检查退出码均为 0。
每套原 record 的 before/after 均为同一干净 source-head；整体 source-before.json 与 source-after.json 原字节相同。
二者 SHA256：`3598451bd2e7338dbc086a7233251e9524aa7d74b6004ef22f24dae34eba8735`。

实际版本：Python 3.12.14、NumPy 2.3.5、Pillow 11.3.0、Ruff 0.15.13。
uv 0.13.7 只安装隔离 Python；项目、测试、格式命令使用原 uv 0.11.3。
运行账户 uid 1000、host ai395；这是匹配上述版本的独立执行，**不是 GitHub hosted run**。

## 原件与核验

`ctrl6240-full-contract-v4.tar.gz` 保存全部 **149** 份原文件，原 bytes 未改。
96284 B；SHA256 `92b190ec60fbbffa0255787177219a98b84d0f50cef1fd9694c7e6e232ffdb5f`。
严格解压得到 819200 B；gzip flag=8，仅在既有解码器上增加有界 FNAME 解析。
CRC32=2322456172、ISIZE、DEFLATE 尾界、tar header 校验及原 manifest 148 项文件大小/SHA 全部吻合。
第 149 项是原 manifest 自身。外层 manifest 列出所有 149 个成员的精确字节/hash。

原 test log、wrapper record、独立 origin probe、runtime、源码前后清单、所有命令日志都在原 archive 内。
origin probe 明确属于独立预执行进程，使用同 cwd/env/test-prefix；不冒称测试 PID 的导入追踪。
runtime-exact.json 中临时 sys.executable 如实保留来源；实际 CI wrapper 使用稳定 project-env/bin/python，并真实检查其存在与 Python 3.12.14。
`driver.py.txt` 与 archive 的 `evidence/driver.py` 字节相同；txt 后缀只是证据路径映射。

## 保留的前次状态

v1：200 个测试执行，199 pass / 1 fail；外部 PYTHONVERBOSE 污染子 CLI stderr，原断言正确拒绝。
v2：0 个测试；外部 help 字符串检查误拒绝。
v3：0 个测试；精确运行时成功，但外部 harness 复用已被 uv 清理的临时解释器。
这些失败原件与请求均保留；v4 没有修改生产源码、测试断言或最低计数。
v1 small evidence tree 为 `743c0836182704d95835abf4256c5e0552290b40`；其完整大 tar 仍保留在原 host，未在本包中假称已归档。

本次研究 actor 调用数为 0；没有模型效益、独立来源确认、全成本、真实冷恢复或原 owner 决定认证。production_owner_decision 仍为 null。
