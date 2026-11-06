# 当前可配置主机的原平台可用性核查

观察完成：2026-11-05T00:41:33.191466+00:00。本次仅调用配置清单、有效能力投影与 typed hardware_snapshot；6 份完整 SDK 原文均核验返回字节数、SHA256、EOF。未调用 process_start / shell_start，未启动构建、测试或持久作业，未改配置。

**未发现可直接补 Intel macOS 或 Windows 原平台门的已配置主机。** 7 个配置别名中没有 Windows；两个 macOS 别名实测均为 Apple M5 / arm64。

| 别名 | 实际系统 / 架构 | CPU | 对原平台门的意义 |
|---|---|---|---|
| mac | darwin / arm64 | Apple M5 | 仅 Mac ARM；不能代替 Intel |
| main | darwin / arm64 | Apple M5 | 仅 Mac ARM；不能代替 Intel |
| ai395 | linux / x86_64 | AMD RYZEN AI MAX+ 395 w/ Radeon 8060S | Linux；不能代替 macOS 或 Windows |
| pocket4 | linux / x86_64 | AMD Ryzen AI 9 HX 370 w/ Radeon 890M | Linux；不能代替 macOS 或 Windows |
| desktop | linux / x86_64 | Intel(R) Xeon(R) CPU E5-2673 v3 @ 2.40GHz | Linux；不能代替 macOS 或 Windows |
| x230 | linux / x86_64 | Intel(R) Core(TM) i5-3230M CPU @ 2.60GHz | Linux；不能代替 macOS 或 Windows |

rog 别名未探测。mac 与 main 返回相同主机名和硬件，不能据此声称两个独立验收环境。所有配置均为当前能力投影，既不证明已具备本项目依赖、工具链和空间，也不证明任何原测试通过。

下一步仍应使用最终精确 head 的原 GitHub Intel macOS / Windows 门，或由已授权管理员提供实际对应原生系统的受控 host。未探测未配置端点，未用 ARM、Linux Intel、Wine、交叉编译或虚拟化结果冒充原平台资格。

完整路径、采样时刻和原文哈希见同目录 host-platform-discovery-report.json。
