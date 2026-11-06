# B15 holdout lock lifecycle: immutable evidence package

[完整评估](ASSESSMENT.zh-CN.md)记录固定源、原 Mac ARM 114P1F、受控 Linux 机制实验和两路径候选的资格边界。原 Mac 具体持锁者仍未知；Rust/项目测试/rustfmt 未执行。

将本目录全部分片与 manifest、restore_packet.py 放在同一目录，运行：

```sh
python restore_packet.py --output /new/empty/holdout-review --replay
```

恢复器拒绝覆盖现有目录，验证所有分片、ZIP、109 个成员与作者 freeze，再重放静态 proof。它不会运行 Rust、OS 机制实验或 CI。完整两份候选源码、原断言、原件与 primary 均在恢复包中；审阅状态以冻结时点为准，后续独审/根审另行绑定。
