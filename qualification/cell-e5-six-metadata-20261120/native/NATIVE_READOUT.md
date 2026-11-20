# Two original E5 source regressions reproduced

Exactly four native children ran once on x230 from pre-native source commit `611a0dd96a648277912d2cd4c9b0a44adc57972b`. Both original upstream regressions failed on the actual buggy runtime and passed on the fixed runtime, with zero test errors, skips or timeouts. The read-only identity check confirms **two additional source materials**. Model calls, training updates and authenticated users are all **zero**; E5 source-growth qualification remains **false**.

| Source | Actual buggy revision | Fixed revision | Complete original function | Before / after |
| --- | --- | --- | --- | --- |
| coady/multimethod #157 | `8b548a3a65bcb4fa028e8c430e3f38956ef53664` | `e7b2c416219b7f8c9c7f67d81613241f01a75825` | `tests/test_subscripts.py::test_callable` | 1 failure (`IndexError` at `args[-1]`) / 1 pass |
| SethMMorton/natsort #196 | `e90771d7c39157d079425b655763938c2709d486` | `e2328c20b62253bea75227b62763ea83874171dc` | `tests/test_compat_locale.py::test_icu_null_string_locale_max_sorts_after_any_bytes` | 1 failure (original sentinel ordering assertion) / 1 pass |

Both complete selected functions have no parameterization or Hypothesis decorator. Original upstream test files and fixtures are byte-identical in each before/after pair; only the corresponding product files come from the buggy or fixed revision. The original 120-second child, 3-second case and one-child-at-a-time budgets are unchanged. No native child was retried. All132 predeclared source/dependency bindings remained unchanged.

## Original failures remain visible

The original collector exited 2 and recorded 0 admitted sources because its JUnit class names contained `replay-1.0-before.work` versus `replay-1.0-after.work` (and the corresponding index1 paths). The original result is retained at `receipts/replay-1/RESULT.json`, SHA-256 `a1691e8dca5760449794ab7c48ea6b07c3141a399fd078b2c31851407afee138`.

The independently frozen reader stripped only the exact known work-directory prefix. It preserved module, function, full parameter name, order and count, verified original stdout/stderr/JUnit hashes and exact runtime/fixture receipts, and did not execute another test. Its result is `receipts/identity-readback-1/READOUT.json`, SHA-256 `352314b2eff9d4c475cc5e896e7dfdc4a47f9e87344b78d08acfa037887fc15c`. It confirms both regressions. The old collector's zero result was not edited into a pass.

Multimethod's metadata first-parent inference is also preserved. The upstream PR was rebased as two commits: the merge result's first parent already contained the fix. Before running any test, the original PR commit history and rebased history both identified `8b548` as the pre-PR buggy revision. `BEFORE_REVISION_CORRECTION.json` and the exact upstream histories record this correction. The project, PR, complete selected test function and final fixed revision stayed the same.

The first dependency setup stopped before native execution because its universal-wheel selector did not accept Hypothesis 6.170.16's platform wheels. The original 7,029,791-byte PyPI metadata, failed setup and original script remain. Recovery selected the same version's CPython 3.12/manylinux x86_64 wheel, with exact SHA verification. The final environment used Python 3.12.3, pytest 9.2.0, pytest-timeout 2.4.0, Hypothesis 6.170.16 and sortedcontainers 2.4.0; offline installation and pip check passed. Both variants used that same environment.

## Scope and costs

Natsort's upstream fixture uses an ICU stub. This evidence does not qualify actual PyICU integration. Hypothesis is imported by the original collection fixture to register an upstream profile; the selected regression generates no Hypothesis examples. Multimethod's same benchmark-marker collection warning is retained in both outputs.

The four native children consumed a measured 2.073065 CPU seconds. The original replay owner took 2.317960 wall seconds; the driver including readback took 2.489800 seconds; the outer binding owner took 2.585887 seconds. These are nested scopes and are not added. Complete host, network, energy and monetary cost remains unknown.

The two projects contribute source materials, not authenticated users or 32 independent trajectories per project. No model was trained or evaluated. The original E5 source-size/budget matrix, unseen acceptance data and learning results remain separate gates. The four other declared repository outcomes remain unchanged. The joint owner must separately validate combining these 2 with its prior 14 sources.

## Complete evidence

`native-originals.tar.gz` contains 292 members (291 original payload files plus their manifest), including all runtime/test snapshots, all four raw outputs and JUnit files, owner receipts, before/after execution manifests, exact dependency wheels, full PyPI metadata and setup recovery. SHA-256: `a4d0d05dbb5929e5d029aa351fb9f36a908d43c2f12ca770b0231cb37f97ec4f`; size 4,667,659 bytes. Every member's bytes and hash were checked after download. Generated installed venv and bytecode caches are omitted; the original wheels and complete installation receipts are retained.

`source-review-originals.tar.gz` retains 101 original acquisition/inspection records, including the superseded first-parent runtime bytes and Git history. SHA-256: `6a9211f55f00cf9d0b199ea7d6b9cfde202dc586db743e6831af400de4c16378`; size 227,188 bytes. Both archive manifests and the most useful original receipts are also available as readable files.
