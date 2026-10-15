# Hepta E1/E2 actual hosted CI failure repair — 2026-10-15

**Research-only.** PR #2072 is Draft / SHADOW / DENY_ALL. This is not a model winner or production promotion.

## Observed failures (not conjecture)

1. [Architecture run 38680673107](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38680673107), **base-merge job 116248886120**, failed at “Verify GitHub prospective merge ref matches this exact candidate,” before Rust tests. Exact event base SHA was `712ae1400f5020b21cb703f719f8f6195fcd7cf4`, while GitHub's prospective PR merge commit `57e2e6846e742a915ad2634b77dde75dd4533511` had two parents: the updated live target branch `09bb40d8bf3a058a34607179d4e0fbdf11a41277` and exact source `92ed007ebbe9fad269adae9f65040b9fb85e6876`. Its tree was `429c2a51cd918f237274a70866a009c38e46b631`. The event baseline had become stale; refusing it was secure but did not evaluate the actual live prospective merge. Unconditional use of the event base SHA for GitHub's moving merge ref caused a false failure.

   **Repair:** The base-merge lane requires the same PR number, open state, exact source head, same repository and base ref; resolves the **live** base commit through its exact GitHub branch ref; validates both parents of GitHub's merge commit and recomputes its tree with `git merge-tree --write-tree` after fetching the verified live commit. A final repeat live-ref query rejects mid-validation base movement. Only after these checks does the lane replace its `BASE_SHA` environment for the synthetic merge, native scope and identity checks. Source-head lane retains its original SHA semantics. Any mismatch fails closed, and source/old/new identities are retained in bounded CI diagnostics.

2. [E1 actual public triplet run 38672788425](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/38672788425), **job 116219535516**, failed at “Install pinned CPU-only research runtime” following successful pinned pip resolution. `import torchcodec` raised `RuntimeError: Could not load libtorchcodec`, specifically missing `libavutil.so.58` for FFmpeg 6 and other unsupported FFmpeg sonames. No pretrained Encoder inference, Head training or NDU result was reached.

   **Repair:** Install the Ubuntu 24.04 FFmpeg 6 **runtime shared libraries**, verify seven expected SONAMEs using `ctypes.CDLL`, and retain the exact `dpkg-query` package version receipts. Preserve pinned `torch==2.10.0`, `torchcodec==0.10.0`, the original frozen weight hashes and all real-result gates. No fake encoder, synthetic stand-in or advisory ignore.

## Non-claims and acceptance

These patches respond to two actual failures; they are **not passed until** the exact latest-head Architecture base-merge AND source-head jobs, E1 real public pilot runtime, E1 core real Granite/mmBERT/ModernBERT CPU experiment, E2 Token Query checkpoint+SGD+NumPy Oracle, and `blocking-ci` return real success for that SHA. FFmpeg package install can still fail on a runner; if so, retain logs and repair from observed evidence. A passing metadata-only V8 canary does not substitute for Rust compilation. E0 original no-change, genuine future NDU, E3–E6, 4,096 Cell host resource and recovery remain separately blocked.

This change touches CI/research documentation only; no runtime production code or physical Cell state is altered.
