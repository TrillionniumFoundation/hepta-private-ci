# 最终格式门：实际范围与源码字节

全部科学运行和单元测试结束后，在 desktop 独立目录执行格式门。未修改原 publication 工作树、任何旧实验或历史 manifest。

## 实际执行

仓库根 AGENTS 要求在 codex-rs 运行 just fmt。c4ae 的真实 justfile 委派给 scripts/format.py；该脚本的默认 scoped 分派只覆盖 scripts、.github 和 sdk/python 下的 Python，遗漏 qualification 下的 Python。因此本次真实 `just fmt` 返回 0，但输出 `No changed files need formatting. Use --all for a full repository check.`；这个返回值不被当作新增 Python 已格式化的证据。

随后使用同一原始脚本的 `python_scripts_formatter_group` 生成命令：`uv run --frozen --project scripts ruff format`，显式传入本轮全部 15 个 pft_*.py，包括 network probe、interventions 与其测试。uv 0.11.3 从现成缓存离线创建独立环境，使用锁定的 Ruff 0.15.13；实际输出 `15 files reformatted`，返回 0。原始 16 个 formatter 配置、脚本、Cargo 清单与强制校验 fixture 保持字节不变。没有运行 cargo formatter 的全 Rust 范围，也没有宣称全仓库格式合格。

15 个文件的静态 AST（排除位置属性）在格式前后完全相同，远端 `git diff --check HEAD -- <15 files>` 返回 0。格式后没有执行测试、编译或重跑实验。共享本地源码已经由逐文件 SHA 核验过的格式后 archive 写回；历史执行源码仍由既有 frozen-executed-source.tar.gz、原 Git commits 与本目录 before-source.tar.gz 保留。

## 真实准备失败也保留

首次 `git clone --shared --no-checkout` 因原库为 promisor partial clone，需要未缓存 blob 而失败。GIT_NO_LAZY_FETCH 阻止了隐式下载全树。随后在新 v2 目录建立独立 Git metadata，通过只读 objects alternates 借用原对象，pin 到 c4ae；16 个必要文件从 GitHub 精确取回并逐个校验 Git blob SHA。真实 sparse index 只 stage 本轮 15 个新增 Python，没有伪造空 crate。

第二次准备发现默认 PATH 缺 uv，因而在执行 formatter 前失败。只读定位现有工具后，显式使用 /home/qian-qi/hcsn-sixwork-tools-20261121-e29f/bin/uv 与现有 uv-cache；没有修改既有 formatter 环境，未进行网络安装。两个失败的记录与终态都保留。

最终执行 job 为 `1a210b1be0b-ffbe-3cb8`，succeeded、exit 0、output_complete 和 output_durable 均为 true，stdout/stderr 完整 EOF。

## 文件

- FORMAT_TERMINAL.json：官方 no-op 与显式 Python backend 的分开状态、全部 15 个前后 SHA、AST 一致性、原依赖不变及完整命令输出。
- PREPARED.json：c4ae、16 个真实依赖、staged 路径和实际官方分派结果。
- before-source.tar.gz、after-source.tar.gz、format.diff：原样源码、格式后源码与全部布局差异。
- REMOTE_STATUS.json、REMOTE_LOGS.json：最终进程完整终态与日志。
- clone-v1-failure.json、path-v2-failure.json 及相应 STATUS/LOGS：两个真实准备阻断。
- TRANSPORT_CHUNKS.json、LOCAL_VERIFICATION.json：版本绑定传输、archive SHA、15 个本地前后源码和静态 AST 校验。

本目录记录只新增，不回写或改写任何科学实验的 source SHA / protocol / seal。
