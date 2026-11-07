# 原始失败日志的可逆存储

本目录保留原 `strict-clippy` 失败。`STATUS.json`、空的 stdout 和 stderr 解压后的
每一个字节保持原样；历史退出码仍为 101，`qualification_complete` 仍为 false。

`strict-clippy.stderr.gz` 是原 stderr 的无损 gzip 存储。编译器输出包含 Rust
内联汇编约束 token；它们属于原始证据，不能为了文本拼写检查而改写。这里只
改变存储编码，没有改动 Codespell 的规则、忽略列表、workflow 或原始检查器。
这不表示历史 Clippy 已经通过，也不能替代新候选的原始 CI。

`ARCHIVE.json` 固定压缩内容和原内容的 SHA-256、长度、原 Git blob 及来源
commit。`readback.py` 同时核对原 STATUS、空 stdout 与原 stderr 的固定身份，
并确认原失败结果没有变化。运行以下命令只核对证据，不运行原生测试或训练：

```sh
python3 qualification/cell-unified-20261106/evidence/native-7e1cd4f0-02/readback.py
```

需要原文件布局时，将三个原文件恢复到一个尚不存在的目录：

```sh
python3 qualification/cell-unified-20261106/evidence/native-7e1cd4f0-02/readback.py --restore-dir /tmp/cell-native-original
```

解压后的 stderr 为 45,345 字节，SHA-256 为
`f88c27cc094d499312489496917d3af4a3fedbad80f3b47bbd8e41c595ef8b10`。
核对通过会报告 `archive_integrity: VERIFIED`；资格决定仍是 `HOLD`。
新生成的 native 记录仍由原 `native_gate.py` 写出原 `.stdout` / `.stderr` 布局。
