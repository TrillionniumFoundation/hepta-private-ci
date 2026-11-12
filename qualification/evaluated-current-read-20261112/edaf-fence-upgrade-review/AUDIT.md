# Fence 已发布兼容与诊断升级审查

## 结论与候选

建议审查一行完整 Action pin 升级候选：`e6b39c80c51cb2b2a39448ddeff74b3b886c0a63`（v0.10.0）→ `c7675fea986c29f1d655753a7a61fd6b4141be8f`（v0.13.0）。它提供已发布的受限兼容处理和更细诊断；不能称本次原失败已经修复，也不能证明 v0.13.0 是本次原因的最小修复版本。

代码仅修改 `.github/workflows/blob-size-policy.yml` 的一行 pin/comment。基线为 `edaf1d9a420dc99336f36b24515eb9c65a97b0da`，原 blob `d867cbc5cae69837bbcaf4646b41da387d0a49f4`，后像 `fb50b3579ad793aae702528c0e7bc5976e182151`，bare tree `eb9de9b1495bc747b37326b0d8fd98c11825d6bf`。保持 first-step、`mode: audit`、`ACTIONS_STEP_DEBUG: "true"`、两处 `contents: read`、0 项用户 allowlist 和原全部后续门。没有 continue-on-error、条件跳过、手工 service 启动、宽限等待或新 workflow。

这是一行使用方改动，但依赖本身从 source735375 到 source64ac 包含169个源提交；不是“一行等于整体安全改动很小”。本次是有明确范围的源码、发布与现有运行证据审查，不是整个 Fence 的重新安全认证。

## 原失败的精确范围

原 edaf workflow run `43267839274` / job `131356473762`，完整9222B日志 SHA256 `ed46a8e0e8f8b8b2781349a903dd3af0bb2d12bc41cd4677c8419d8ab2bc8538`，已重新读取验证。
实际 Action v0.10.0 / source `735375fadb54cc11a7d2d10642b3150f93fe8720`；Runner2.338.2，Ubuntu24.04.5，镜像 `20261111.370.1`，Azure westus3。输入为 audit、原 bootstrap_v5、0 allowlist。
原 service 在 readiness 前退出，唯一分类码 `local_control_inventory_unavailable`；原 journal 没有 `unavailable_inputs`、attempts、startup_check 或 ownership_detail。可见的 socket probe 命令不是失败原因的判定。
随后 checkout 未执行导致本地 clean-worktree action 找不到，post hook 缺少 active mount evidence，均保留为原记录；本候选不把这些后果改成通过。

旧错误码可由进程/FD/cgroup、IPv4/IPv6/Unix采集、identity drift、socket ownership、reachability 等不同原原因产生。没有细项就不能推定是 snapd、缺owner、网络策略或等待时间。

## 最早发布的相关能力

| 首次版本 | 已核原源变化 | 与本次原因的关系 |
|---|---|---|
| v0.10.2（2026-09-14） | 一般 acquisition 的有界重采样；基础 fence_local_control 诊断 | 只有原失败细项显示相应采集问题才可联系 |
| v0.10.4（2026-09-30） | 精确身份/端点的 uuidd activation/idle | 原日志未指认 uuidd |
| v0.11.1（2026-10-14） | local_control 与0.10.4、0.11.0、0.12.0/1/2逐字相同 | 不是后来缺owner重采样或snapd修复 |
| v0.12.3（2026-10-23） | 只采集TCP listener的netlink路径；不完整kernel dump重新采集 | 原日志不能确定是TCP表问题 |
| v0.12.4（2026-10-26） | 已知且完全无owner的socket在其余合同一致时受限重采样 | 从不把不完整采样接受为完整 |
| v0.12.5（2026-10-27） | 保留并报告第一个resident失败scan | 是诊断改进，不能证明旧startup原因已修 |
| v0.12.6（2026-11-02） | startup_check及四种ownership_detail闭集 | 是最早具备该细分类的已发布版本 |
| v0.13.0（2026-11-09） | 受保护packaged snapd双socket激活；拒绝退出中的不完整owner | 最早包含该精确兼容修复，尚未证明原失败由它触发 |

每行 source/Action/blob/SHA256 与关键commit见 RELEASE_FEATURES.json。若目标仅是丰富启动失败分类，v0.12.6已经具备；这里建议v0.13.0是兼顾当前正式兼容处理的候选，并不回溯改写“最低已证明修复”。

## 已实际核对的失败关闭与权限边界

旧/新 `verify_complete_local_control_observation` 函数逐字相同：unstable、超界、unavailable_inputs非空、reachability/ownership不完整仍返回错误。原3次采样上限、50ms间隔、5秒观察期限及进程/FD/owner/listener限额未增。
缺owner路径使用 `Owners::ForRetryOnly`，仅决定是否在原预算内重采样；最终验证仍使用完整采样与原身份匹配。观察到未审身份、部分不完整owner、超界、畸形行等不能借此放行。
v0.13的snapd规则限定原两socket、PID1/systemd、root snapd的精确路径/cgroup、实际device/inode和root-owned不可写包路径。换进程、改路径、伪造/退出不完整不能作为合法激活接受。
Action旧/新 action.yml完全相同（blob97e91823…），仍node24；新main遇启动异常设置exitCode1，诊断只渲染有限枚举，不将诊断本身作成功证据。
不新增项目网络allowlist。上游版本确有新增“经过审查的host身份”规则，不能把这误称为vendor所有允许集合完全未变；它们与网络allowlist不同。
audit继续是观察模式：健康日志也明确 `protection_available:false` / `ready_observation_only`。不将audit成功等价于block保护或原owner资格。

## 官方发布证明与Ubuntu24 canary

官方v0.13.0已非draft、非prerelease；发布说明给出完整distribution pin c767…与reviewed source64ac…。distribution仅以source64ac为父且GitHub签名verification=valid；新增恰为binary和bundle manifest。
bundle manifest中的binary SHA256 `1a1ac7ad60216e7803403645c202e8c8a4e738326350ce340f8138df1c9a5e04` 与官方release asset metadata一致。
实际release run `42684760545` / verify-release job `129393561886` 原日志与job steps成功，包含完整发布资产验证。本审查保全该官方验证记录；未自行下载/重验binary或执行attestation工具。

最新已读scheduled canary run `43218455499`（2026-11-12，attempt1）：
- first-step Ubuntu24 audit job `131183598570`：c767…，0用户allowlist，contents:read，启动成功且post evidence verified；明确观察模式。
- first-step Ubuntu24 block job `131183598903`：同pin，0用户allowlist，contents:read，启动及post验证成功。
- 两者实际镜像均为 `20261101.360.1`，不是原故障镜像 `20261111.370.1`。同为Ubuntu24.04.5/Runner2.338.2不能抹掉镜像差异。
- 所以新版在故障镜像的兼容性仍未实测；不由另主机green推断旧故障根因消失。

官方issue223仍OPEN。其维护者明确：v0.12.6两block canary通过而原socket ownership失败没有复现，但原原因未知，继续保留问题。该官方谨慎结论与本审查相同，不将另一次成功当根因证明。

## 后续可执行边界

本轮只创建immutable code/evidence tree；没有commit/ref更新、没有workflow派发、没有h或actor。
root审查并按原流程合入后，保留下一次真实自动workflow的Action/source、runner image、原首attempt、startup分类、全部后续门与post evidence。新镜像仍失败时保留错误并使用新增细项定位；不能增加allowlist、关门或改未知为成功。
原edaf/286c失败保持原身份。新版本将来成功只能支持该次新source/image调用通过，不能证明旧原因已完全查明。
