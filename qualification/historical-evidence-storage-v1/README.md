# 历史证据的可逆存储

`ARCHIVE.json` 固定五份历史 JSON 输出或预注册输入的原路径、长度、SHA-256、
Git blob 与 gzip 存储身份。原内容来自 commit
`3aed50bf51249dbeae4506663b7029eef623ca14`。这里只转换存储编码，原始 JSON
中的 Unicode 样例、正则、成本、失败与资格决定均未改写。

三份原 inventory/index、全部历史回执及 `EXECUTED_SOURCE` 保留原字节。
当前 `receipt_verifier.read_capture` 在原路径缺失时读取相邻 gzip，仍有原
512,000 字节上限，且拒绝重复存储、链接、损坏 gzip 或超限解压。原回执中的
SHA、长度与 JSON 一致性检查继续使用解压后的原字节；不会以压缩文件的 SHA
代替原身份。当前 decision replay 的原交付 inventory 核对使用相同读取方式。
新的 replay 会冻结其实际使用的 receipt verifier；旧冻结源码不改。

Joint recovery 从它原有的模型归档读取 `protocol.json`，不依赖本地历史展示
副本。原 `EVIDENCE-INDEX.json` 仍描述解压后的历史协议。历史 README 中的
原路径可通过以下工具恢复；不将旧自由文本质量结果提升为成功。

在仓库根目录核对全部字节和三个原阶段回执：

```sh
python3 qualification/historical-evidence-storage-v1/readback.py
```

恢复五份原文件到一个尚不存在的目录，供只接受原始布局的历史工具使用：

```sh
python3 qualification/historical-evidence-storage-v1/readback.py --restore-dir /tmp/hepta-original-evidence
```

核对成功只报告 `archive_integrity: VERIFIED`，资格仍为 `HOLD`。该命令不运行
模型、训练、原生 worker 或原 CI。Codespell 的原检查器、规则、忽略列表没有
变化；旧 head 的 Codespell 失败及全部原 CI 分母继续保留。
