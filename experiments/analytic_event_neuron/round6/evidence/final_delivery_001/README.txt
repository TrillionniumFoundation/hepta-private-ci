HEPTA ROUND6 — 封存研究交付包

发布控制提交: 3d037bf23bf33eaedceaef0cee9835981ae97156
BUNDLE.json SHA256: 539d5b59740faeb3e96f68428d7af093e48ec47156e14de2ab0b346e16426bfc
FINAL_PUBLICATION.json SHA256: ab6265091254e1ed74b896602e3156dabb0d21900dcec54e296a84fed4f0e2b3

本 ZIP 包含:
  HEPTA_ROUND6_REPORT.md           中文完整验收报告（证据链接固定到上述提交）
  utility_and_calibration.png     报告图表，可离线显示
  REPRODUCE.md                    完整复现指南与固定结果/审计身份
  artifact_bundle.py              标准库校验和恢复工具
  FINAL_PUBLICATION.json          外部发布、远端回读和恢复索引
  final_bundle_001/BUNDLE.json    内层封存证据清单
  final_bundle_001/part-*.bin      全部 451 个原始二进制分片

外层 ZIP 不再重复保存 archive.tar.gz。分片已经是完整压缩归档的连续字节。
恢复后直接得到部分研究仓库根目录，其中包含完整研究证据与继承源码；
它不是全历史 Git 仓库，也不包含完整 codex-rs 构建工作区。

解压 ZIP 到新目录后，在包含本 README.txt 的目录中执行以下 Bash 命令。
将第一行替换成实际解压目录的绝对路径。Python 工具只需标准库；这里不训练模型。

  cd /absolute/path/to/extracted/HEPTA_ROUND6_BUNDLE
  python -B artifact_bundle.py verify final_bundle_001 \
    --expected-manifest-sha256 539d5b59740faeb3e96f68428d7af093e48ec47156e14de2ab0b346e16426bfc
  hepta_final_parent=$(mktemp -d -t hepta-round6-final.XXXXXX)
  python -B artifact_bundle.py restore final_bundle_001 "$hepta_final_parent/research" \
    --expected-manifest-sha256 539d5b59740faeb3e96f68428d7af093e48ec47156e14de2ab0b346e16426bfc

目标 research 必须尚不存在。工具校验全部分片、完整归档和成员后才创建恢复目录，
然后回读成员并保留可执行权限。分片目录旁需要归档重组的临时空间。
完整恢复目标为 "$hepta_final_parent/research"，无额外 hepta-analytic 外层目录。

在记录的数值环境中，再执行指南中的精确冻结验证（不会重训）:

  cd "$hepta_final_parent/research"
  hepta_python=/opt/codex/runtimes/codex-primary-runtime/dependencies/python/bin/python
  "$hepta_python" -B -m experiments.analytic_event_neuron.round6.lifecycle verify \
    --run-dir experiments/analytic_event_neuron/round6/evidence/registered_001 \
    --expected-freeze-sha256 1f4d994da28d3bd61853a904d3e9da03b6ea6c90fe9d680e217f976656450ca1

数值环境与历史 native 二进制身份详见 REPRODUCE.md；不同环境可以进行字节验真，
但不能宣称通过原始环境的精确 lifecycle 验证。改变训练、种子或环境属于新实验身份。
GitHub 证据链接需要相应私有仓库读取权限；恢复后的对应本地文件可直接查看。

本轮确认与独立审计已完成；两项预登记主要收益优越性门槛均未通过。
运行时证据限于本地研究 owner、已登记的恢复范围和实际测量环境，未激活生产 Agentd。
无需重新训练即可阅读和验证这批不可变证据。外层 ZIP 自身的校验收据单独发布，
不放入 ZIP 内，以避免自哈希循环。
