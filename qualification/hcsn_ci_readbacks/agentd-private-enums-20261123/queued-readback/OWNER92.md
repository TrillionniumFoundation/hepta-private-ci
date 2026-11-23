# Native Agentd owner regression roster

These runs compare the fixed 62 ordinary and 30 real-UID0 cases from the nine-repair composition. Both native musl libtests execute the same roster with one Rust test thread. Thirty gated cases use the original root fixture and an in-process UID/EUID assertion immediately before exec. All four runs use the same roster, source test wrappers, driver and UID0 setup. SHA-256 for the actual roster bytes is `92a1f91f2fda5cef559fee7957821f65ed8c0f4d14b4df057032204cda158837`.

The earlier pair used e327 and 43e5. The baseline passed 62 ordinary and 29 UID0 cases. Its only failure was the queued resident cancellation test expecting `Unavailable` at line 112. The combined tree passed all 92 in that particular run. The accompanying observation ZIP and separate twenty-process repeat establish the observed error values and the result after waiting for the cancelling worker to hand back its lane permit. [Earlier pair](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/45133193126)

The synchronized pair uses the direct children 3002afb8 and e1969bcf. GitHub Actions restores the same original musl target on the same Bazel cache scope and verifies each ELF SHA-256 against the earlier 20-process fixture run before starting this larger roster. The checkout pins the Git blobs of the original case list (`f42121c5e9ef50663869a3107488f0477287c07e`), native driver (`729c412928cdf08c7edf80f58c0faafb37516cd3`) and root setup (`aa737d0502b9f0842bb8718fe76c127c5aaaec89`). [Exact workflow](https://github.com/TrillionniumFoundation/hepta-private-ci/blob/b64dec78b13b96829ed51b48f52ce5919fa553f0/.github/workflows/agentd-resident-sync-owner92.yml) · [Synchronized pair](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/45138043396/job/137568934085)

| Source | Ordinary cases | Rust elapsed | Effective/real UID0 cases | Rust elapsed |
|---|---:|---:|---:|---:|
| e327 with synchronized test (3002) | 62/62 | 135.99 s | 30/30 | 18.62 s |
| 43e5 with synchronized test (e196) | 62/62 | 137.50 s | 30/30 | 18.18 s |

The new original artifact (14800987559) contains 32,023 bytes. The earlier original artifact (14799557174) contains 33,440 bytes. These timings are the Rust harness wall-clock durations per test batch. The full repository, the complete Agentd libtest catalog and the strict compiler gate have different scopes.

```sh
python3 verify_owner92.py old92.zip sync92.zip --sync-sha256 41644ef5083521419e8670fa0ddfb73e0fd74a3d46c582d93d59675a0c1e4aa6
```
