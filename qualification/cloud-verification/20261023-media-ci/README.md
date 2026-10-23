# Dedicated codec CI false-green repair

Base #3563 exact `a88f2832f2a1a4d3734c1c88f76977dcc9b98ff1`. Independent branch; no v4/native chain changes. Final source `d847bb289159d8857f53cdcf5de79636e18df105`, tree `b9c7da14102e0e7ab5b611859e58bb8701e3c91a`, draft #3610. All three remote files matched the independent review. Exact-source rerun: real media 21 passed with zero skips; full suite 107 passed with zero skips; scoped Ruff, compileall and diff checks passed. Source worktree clean. Hosted dedicated run 40034870009/job 120691752889 was queued at evidence publication; no hosted acceptance is claimed here.

## Original failure

Original run 39964510679 / job 120450755349 reported success despite both `ffmpeg` and `ffprobe` being absent. The actual log verifies the correct base SHA, then reports `command not found` and `Ran 21 tests in 0.000s; OK (skipped=21)`. The shell pipelines ended with successful `head`, masking tool exit status. The ordinary unittest suite legitimately skips codec-dependent classes when codecs are unavailable. This combination meant the dedicated job established no real-codec coverage. `old-false-green.log` preserves the original log; old green is not used as acceptance evidence.

## Repair

The dedicated workflow explicitly installs FFmpeg from the Ubuntu runner's configured official package source using apt-get (no added repository or credentials), uses explicit bash and direct `command -v`/version commands without pipelines, and retains exact-source verification. A standard-library runner requires both executable tools with checked, time-bounded version invocations, discovers the unchanged 21 real media tests, and rejects zero tests, any skip, expected failures, errors, failures or unexpected successes. Workflow also executes the gate regression tests and full signed/media suite. Original format checks and generic skip decorators are unchanged.

Six gate tests cover the real entrypoint with an empty PATH, each missing tool, broken tool execution, zero/all-skipped/partially-skipped suites, failed test and successful execution. An independent PATH-empty experiment confirms dedicated acceptance exits 1 while generic media discovery retains exit 0 with 21 skips. This distinction is intentional: generic lightweight CI is not codec acceptance.

## Local commands and environment

Linux x86_64, Python 3.12.14, Ruff 0.15.13; installed Debian FFmpeg/FFprobe 7.1.5-0+deb13u1. No local installation was needed. No added Python dependencies. From repository root:

```sh
python qualification/ndu-dmgp-shadow/run_codec_acceptance.py
python -m unittest discover -s qualification/ndu-dmgp-shadow -v
/workspace/verification-3567/pyenv/bin/python -m ruff check qualification/ndu-dmgp-shadow/run_codec_acceptance.py qualification/ndu-dmgp-shadow/test_codec_acceptance.py
python -m compileall -q qualification/ndu-dmgp-shadow
/workspace/cargo/bin/just fmt
git diff --check
```

Working-source results: media **21 passed, zero skips**; full suite **107 passed, zero skips** (original 101 plus six gate tests). Scoped Ruff/compileall/diff checks passed; fmt found no changed Rust files. Exact-published-source rerun logs are separate. Independent complete three-file review and source hashes are included. No tests or format gates were removed or weakened.

## Boundaries

This repairs dedicated structural-codec CI admission. Encoded signal fixtures do not prove real neural model execution, semantic truth, independent signer custody, hardware efficiency, or scientific closure. Existing synthetic adverse results and SHADOW_ONLY / DENY_ALL / HOLD_NO_GO remain. Existing test fixtures are not production credentials. No provider, model download, paid service, security-setting change, merge or deployment. Full repository/Rust/platform validation is outside this Python/workflow change. Hosted CI must execute codecs on the new exact HEAD; queued jobs and old all-skip success are not acceptance.
