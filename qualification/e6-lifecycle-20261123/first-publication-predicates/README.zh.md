# cold01 首次发布事实的离线复算

在同一份失败捕获上，原提交 `61503a7d` 首组 16 项条件中有 14 项为真。第 12 项首先失败。首次发布保存的目标 observation 是 `ce848407…`，旧代码用最终已 drain 的 observation `4a7b04d6…` 比对它。逐项计算时，第 13 项要求最终 journal 仍为 genesis，也为假。原 Rust 的短路求值在第 12 项停止。

修复提交 `bf6d5190` 使用同一 journal 的原始 genesis observation，逐字节计算得到 `ce848407…`，并要求最终态已 drain。修复后的首组 16 项在该旧捕获上全部为真，后续 4 项历史时间关系也全部为真。这项结果解释了原 FIRST-PUBLISH 失败。新版本完成实际冷启动、等待租约过期、第三次进程读回和 Adopt 仍需各自的运行证据。

## 从已发布工件复算

使用 private CI 仓库提交 `8b0e87d2e41a680977f2ea28d9ec8f6da769d33b`。在该 Git checkout 中，将本目录的绝对路径赋给 `REPLAY_DIR`。下列命令只读取旧包，通过摘要选定原始 gzip，不需要 Rust、外部 Python 依赖或网络。

```bash
python3 - <<'PY'
import hashlib
import pathlib
import tarfile
base = pathlib.Path("evidence/e6-terminal-originals-20261121-ac5459/cold01-fix-checkpoint/parts")
parts = sorted(base.glob("cold01-fix-format-and-physical-originals.tar.xz.part-*.bin"))
assert len(parts) == 1
outer = parts[0]
assert outer.stat().st_size == 299836
assert hashlib.sha256(outer.read_bytes()).hexdigest() == "54f24989f0ef8f7f8997ce97456302185fcfcd40a86d3d910ed90091a554a863"
wanted = "47364fc10bd07779339fbce47456586bab173a01b23ad45c83151f703f7fa5d4"
with tarfile.open(outer, "r:xz") as archive:
    candidates = [archive.extractfile(item).read() for item in archive
                  if item.isfile() and item.size == 48927]
matches = [item for item in candidates if hashlib.sha256(item).hexdigest() == wanted]
assert len(matches) >= 1 and all(item == matches[0] for item in matches)
pathlib.Path("original-physical-data.tar.gz").write_bytes(matches[0])
PY
python3 "$REPLAY_DIR/replay.py" original-physical-data.tar.gz > actual-predicates.json
cmp actual-predicates.json "$REPLAY_DIR/PREDICATES.json"
```

本次输入另从冻结的 ai395 物理只读作业 `1a1fe1384e2-ffbe-2069` 的 66,804 字节完整 stdout 解出。原 gzip 包含 1 份收集表与 34 份原件，程序逐一核对收集表中的路径、长度与 SHA-256。两个版本的关联 Rust 文件及其 SHA-256 见 `SOURCE_PINS.json`，两个实际修改文件的 Git diff 见 `SOURCE.diff`。

## 计算范围

- 按 Rust 的域分隔 SHA-256 和结构字段序列化顺序复算 40 字节 guarded header、单个 drain 帧、224 字节 witness、genesis 与最终 checkpoint，以及两个 observation digest。在冻结字节上核对历史观察器先后两次读取的稳定性以既有物理收集回执为依据。
- 按 HEPLCP02 结构解析 1,117 字节原初始快照。第 823 字节处为 8 字节大端 work expiry，值为 1,795,261,752 秒。完整遍历该快照的字段边界，核对空初始收据列表和注册的 head digest。
- 按 accepted publication、registered profile、completed CURRENT、signed grant 与 witness 的原字段逐项比对。`PREDICATES.json` 标出了在 11 月 21 日已验过的两项。复算覆盖首次发布判定使用的数据条件。Rust 原初始化器、文件描述符和权限检查、活体时钟与签发流程未在此次离线计算中执行。
