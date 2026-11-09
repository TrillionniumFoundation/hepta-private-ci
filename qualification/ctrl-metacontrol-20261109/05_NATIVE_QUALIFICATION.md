# Native content-chain qualification

The explicit fixture test calls the real `EpisodeHost.run()`, Tesseract, Torch
actor, mandatory Landlock/seccomp launcher, persisted delivery and independent
scorer. It also checks observed-wire mutation and a wrong model pin. The fixture
is generated separately from runtime read roots and never uses real corpus data.

```sh
PYTHONPATH=scripts:. python -m unittest \
  ndu_real_runtime.test_content_identity_native -v
```

The local execution entered **zero test methods** and raised **one setup error**:
`Mandatory Landlock ABI >=3 is unavailable: abi=-1, errno=38`.
The actor did not start; `enforced_before_actor_exec=false`, `launch_receipt=null`
and no host exchanges were observed. This is **HOLD_NATIVE_ENVIRONMENT**, not a
passing native test. No enforcement bypass or alternative launcher was used.

A narrowly scoped GitHub Actions job runs the same qualification on Ubuntu 24.04
and retains its result. Required prerequisites remain mandatory. Its tested
synthetic merge commit is recorded separately from the PR's source head.
CI success, if observed, would establish fixture integration on that host; it
would not resolve the six historical #5450 failures or establish policy gains.
