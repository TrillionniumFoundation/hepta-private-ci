# Source51 修复与实际应用证据

本组封存 source51 注册、两处精确修复、真实 launcher 对照、实际 apply 成功及 r26 的初始启动输入。它不包含 r26 的测试终态。科学结论保持 **HOLD**，authority 保持 **DENY_ALL**。

## 身份与阶段

| 项目 | 封存事实 |
| --- | --- |
| GitData commit | e28b0f385ee882f842911044958b2810f62f6379 |
| Source tree | 763c8d2b4089f6e9806c3bbb68fa247bc2f6af36 |
| Parent source50 | 1fdd647b0ecb235530e8b88bbea45b3d3762906f / ea48acf562499192a25e05ae28926a32632dee62 |
| 变更清单 | 194 路径，180 Rust；相对 source50 只改两条既有路径 |
| Native HEAD | bef6fa7645df9df12b69fda499e97eed25de6c75；本组不把 GitData commit 写成 checkout |
| Apply | 三条原 Git 命令 exit0，原 outer 自然0，前后源码及双锁 guard 通过 |
| r26 | 仅原 job 1a1b1b739ee-fc05-7a70 的初始 launched 快照；三阶段结果均 null |
| 既有失败 | r24 仍为 1561 PASS / 3 FAIL / 0 TIMEOUT / 3 reported skip；r25 未执行 |

## 改动与证据强度

exec-server 的测试 launcher 在安装新的 child PATH shim 之前，使用已有生产函数寻找 system bwrap；只有找不到时使用仓库二进制。选定程序的后续运行错误继续传播，没有失败后换程序。原 shim 的完整参数、FD、环境传递、隔离配置及测试断言保留。

受控对照保留同一组 --unshare-user / --unshare-net / --ro-bind 参数：固定 /usr/bin/bwrap 0.11.1 返回0，固定仓库 bwrap 返回1并留下原61字节 loopback 错误。对照未运行 Rust，不证明所有 bwrap 后端合格，也没有确定该错误的具体 LSM 或 netlink errno 根因。

network-proxy 的改动只为直接 CONNECT policy 测试配置现有 allow_local_binding 选项，保留生产默认值和独立地址 guard 测试。两个 candidate 的原文、补丁和独立审查均保留。

## 读取入口

- [闭合范围](CLOSURE.json) 与 [独立读回](INDEPENDENT-READBACK.json)：重新校验两条补丁正反、7棵原始直接 Git tree、实际 commit、7成员输入包、三条 Git raw/receipt/stream/outer 和 r26 的冻结输入。
- [原件映射](SOURCE-DESTINATION-MAPPING.json)：每个原路径、原字节 pin、当前存放位置。大于等于16KiB的同字节重复件只存一次；原件自身的相对引用可通过此映射解析。
- [附件清单](ATTACHMENT-MANIFEST.json) 与 [二进制计划](BINARY-PLAN.json)：逐件原始 SHA256/Git blob；输入 tar 未改写。
- registration/ 保留早期 pending/false 原字段及后来的实际注册和 root 授权；native-apply/ 保留实际运行原件；r26-launch/ 仅保留初始启动与控制器查询错误。控制器查询错误不视作测试结果。
- reviews/ 与候选内 independent-review/ 保留各审查者原始范围；新附件读回不冒充先前报告的原字节。

只读复算：运行本组 tools/assemble_attachment.py --verify-only <本组目录>。该入口只解析与哈希本组文件，不导入或运行任何被封存的 runner，不访问 native，不执行 Git、Rust 或 formatter。

本组不重复194源码目录。完整清单保留，变更的两对源码保留；对其余192路径的独立结论限定为与 source50 清单逐项一致，实际 full-source 核验以原 native guard 为证。最终 fix/fmt、完整项目和默认工作区门须等待各自独立闭合记录。
