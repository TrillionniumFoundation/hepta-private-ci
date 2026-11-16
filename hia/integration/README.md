# HIA cross-owner premerge guard

**HOLD, not a qualified build.** This deliberately fail-closed inventory is pinned to Draft [#6382](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6382) at `74d1c0eb` and Draft [#6395](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/6395) at `d2fb9ecd`. It is read-only; no native dispatch, dependencies, default selection or existing tests are changed.

Run `python -m unittest discover -s hia/integration -p test_premerge_gate.py -v`, then `python hia/integration/premerge_gate.py hia/integration/snapshot_6382_6395.json --output /tmp/hia-premerge-hold.json`. The second command intentionally exits **2**; no comparison of unmerged branches constitutes a tested combined tree.

The heads list 17 and 19 HIA module names (29 distinct, 7 common). They have seven divergent source paths, including the workflow, toolchain, installed consumer, canonical docs and `hia/template_render.hepta`. Both native implementations export `codex_hia_template_render` but use different v8 stateful vs v9 full-frame contracts. Keep **both** `prefix_admission` and `token_budget` scalar profiles and every unique HIA module.

Closure requires a reviewed single ABI, exact combined Git tree, full native link, original/public behavior and no-write tests, both default/native installed consumers, strict lint, platform and performance acceptance. This guard cannot approve default release, whole Codex migration, or deletion of the existing Rust implementation. Refresh the pins on every head change and retain historical failures.
