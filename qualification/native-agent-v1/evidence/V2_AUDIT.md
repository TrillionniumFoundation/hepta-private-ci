# V2 independent evidence audit

The corrected audit was rerun locally against all six original V2 REPORT.json files and adjacent captures. This is a read-only audit; no model or benchmark was rerun. Absolute report paths differ from the remote summary.

**Verified: 45/45 measured cases and 6/6 warmups correct; all 102 captured requests match their effective gateway hash; all six actual sampler CPU/elapsed ratios are below the unchanged 5% comparison threshold. All 1377 evidence files retained their SHA256 values.**

## Actual resource and timing results

CPU columns are observed scoped totals, overlap, and must not be added. They include startup, warmup, observer and shutdown. PSS is the sampled complete-selected-PID peak, not global peak memory.

| Mode / lane | Measured completed-row median / sample p95 ms | Lane elapsed s | Sampler CPU / elapsed | Complete PSS MiB (complete / incomplete samples) | Observed cgroup / process CPU s | Cgroups with unknown CPU / all |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| replay / app-server | 2355.96 / 2621.41 | 25.277 | 3.995% | 234.535 (46 / 4) | 12.967 / 10.290 | 8 / 11 |
| replay / facade | 2313.78 / 2614.06 | 24.212 | 4.019% | 212.399 (48 / 0) | 12.601 / 9.750 | 6 / 11 |
| replay / native | 2101.29 / 2182.21 | 21.640 | 1.973% | 39.454 (42 / 2) | 8.554 / 6.810 | 8 / 11 |
| live / app-server | 9336.59 / 11753.66 | 76.288 | 3.306% | 228.653 (147 / 2) | 13.118 / 10.920 | 3 / 8 |
| live / facade | 7310.97 / 9717.25 | 58.364 | 3.492% | 204.708 (112 / 2) | 11.581 / 8.900 | 2 / 8 |
| live / native | 6251.52 / 7363.07 | 46.922 | 1.683% | 40.049 (93 / 1) | 6.923 / 5.340 | 4 / 8 |

**CPU coverage is materially incomplete.** Detached cgroups often disappeared before first polling: replay has 8/6/8 unknown cgroup CPU values for App Server/facade/native; live has 3/2/4. Every detached job lacks a final cgroup CPU endpoint (10 per replay lane, 7 per live lane). No counter reset or runtime-discovery error was recorded. Unknown CPU was not converted to zero. These data do not establish complete-system CPU savings.

All actual intervals are 500ms post-sample waits; observed largest gaps are 0.512–0.537s. All samples used scoped enumeration, with no recorded full-/proc fallback. Ordinary process/task exits and unreadable PSS remain explicit coverage gaps. Even the facade replay 48/48 complete PSS samples do not prove full temporal discovery.

## Actual live model usage and budgets

Measured usage excludes warmup. Cached input below is already included in input, not additional consumption. Replay usage is synthetic and is not actual token use.

| Lane | Measured input | Cached input subset | Output | Total | Warmup total separately | Max raw / effective request bytes | Max completed output tokens |
| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |
| app-server | 29820 | 26241 | 975 | 30795 | 5072 | 6281 / 6305 | 161 |
| facade | 30158 | 26578 | 801 | 30959 | 5087 | 6084 / 6108 | 172 |
| native | 16986 | 16205 | 780 | 17766 | 2923 | 1646 / 1646 | 142 |

Every case has two captured model calls, one executed tool call and one generated tool call. Every effective max_output_tokens is 256; all original/effective requests are below 65536 bytes, all completed output token counts are at most 256, and all cases stay within 4 model / 3 tool calls. The existing pure tool-feedback capture audit was also rerun for all 51 cases and again matched each final answer to its original tool call and feedback. This did not rerun tools or independently recompute fixture arithmetic.

All actual model fields are qwen38-flash-next-uc. The final user task text is byte-identical across the three lanes for every corresponding case, including warmups. Full input protocols differ: Codex store=false, parallel_tool_calls=true, tool strict=false, reasoning={}; native store=true, parallel_tool_calls=false, strict=true, and no reasoning field. Context size and cached-token usage differ. Provider weights/deployment identity and optional reasoning-token usage remain unknown.

## Frozen sources and execution identity

All five harness source fingerprints in every REPORT exactly match FORMAL_PLAN_V2.json. The audit script also matches its frozen hash. Recorded start times follow the recorded plan freeze; the six-lane sequence matches the plan and reported run windows do not overlap. All executor hashes and the common helper hash match V1; the helper also matches the frozen native binary hash. Parent CPU quota is 400000/100000 and memory.max is 8589934592 in all six reports. Effective cpuset and nice=10 are not independently evidenced by these reports.

- benchmark_v2.py: `cc8c7c35005fcf1ab9abd2e09c19cc7ebf7f2c82da08cfc1437cb0776089a69c`
- process_metrics_v2.py: `e823227becebde2d15a003107bdb17b35693632eb8373aab854d47624aa7f4f4`
- Corrected audit script: `669bfbee520e370d6ac7c42d67df90f76f48b294a441187d8974207e61ac7288`
- Original archive: `ac1bd04a5c688fab250c161cf7dbfa0323a19a39f76cc706cbe87a2fd3ff9cab`

The plan declares official source 360319d8dee62d87e2d59fc0c21805d79519cfed. Source revision and compiler provenance for compiled binaries require the separate build evidence; matching REPORT hashes does not independently reconstruct those builds. Full source fingerprints and per-lane checks are preserved in V2_AUDIT.json.

## Supported interpretation

In this bounded three-task experiment, the native lane successfully completes the same tasks and has a substantially lower observed complete-selected-PID PSS peak. Compared with App Server/facade, its V2 replay medians are 10.81%/9.18% lower; live medians are 33.04%/14.49% lower. These describe this sample and these input/context configurations, not a universal or pure-IPC speedup.

The executor and runtime-helper binary hashes are unchanged between V1 and V2. Different sampling cadence means V1-to-V2 PSS changes cannot be called implementation memory reductions. Small sequential runs, provider/load/cache variability, distinct full model inputs, missing short-lived CPU and sampling gaps remain material limits. With n=9 or n=6, nearest-rank p95 is the sample maximum. No general-agent, production authority or recovery qualification follows from these successful normal-run cases.
