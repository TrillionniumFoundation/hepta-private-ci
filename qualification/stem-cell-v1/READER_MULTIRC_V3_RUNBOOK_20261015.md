# MultiRC Reader v3: local reproduction, 2026-10-15

This runbook reproduces the local shared Granite97 → query-conditioned Reader →
frozen verifier/critic → online native Q32 control pipeline. Run from one fixed
checkout containing code PRs [#2275](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/2275),
[#2276](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/2276),
[#2277](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/2277),
[#2278](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/2278),
[#2279](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/2279),
[#2280](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/2280),
[#2281](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/2281), and
[#2282](https://github.com/TrillionniumFoundation/hepta-private-ci/pull/2282).
The procedure uses local execution and persisted receipts; no hosted CI result
or waiting is part of the experiment. Keep downloaded data, weights, feature
tensors and generated checkpoints outside the repository; do not upload them.

## Environment and immutable inputs

The tested environment was Python 3.12.14, torch 2.6.0+cpu, transformers 4.57.1,
huggingface-hub 0.36.2, numpy 2.5.4, tokenizers 0.22.2 and safetensors 0.8.0.
Rust/cargo 1.95.0 and Clippy must be available through the selected toolchain.
Use fresh output directories; stage commands reject existing destinations.

```bash
REPO=/absolute/path/to/hepta-private-ci
RUN=/absolute/path/outside/repository/reader-multirc-v3
mkdir -p "$RUN"
python3.12 -m venv "$RUN/venv"
PY="$RUN/venv/bin/python"
"$PY" -m pip install torch==2.6.0 --index-url https://download.pytorch.org/whl/cpu
"$PY" -m pip install transformers==4.57.1 huggingface-hub==0.36.2 \
  numpy==2.5.4 tokenizers==0.22.2 safetensors==0.8.0
cd "$REPO/qualification/stem-cell-v1"
```

Optionally save `pip freeze` and `importlib.metadata.version(...)` output beside
the run. The Encoder loader checks Transformers 4.57.1; a different installed
version is not an equivalent reproduction.

Official source: <https://dl.fbaipublicfiles.com/glue/superglue/data/v2/MultiRC.zip>.
The archive has 1,116,225 bytes and SHA256
`b3cd440856e72eb166b2edcd37b798455f1ebd51f2c3de64c0c2a4e1971d2737`.
Use a bounded stdlib download and read only the two allowlisted ZIP members:

```bash
READER_SOURCE_DIR="$RUN/source" "$PY" - <<'PY'
import hashlib, io, json, os, urllib.request, zipfile
from pathlib import Path
root = Path(os.environ["READER_SOURCE_DIR"])
root.mkdir(parents=True, exist_ok=False)
url = "https://dl.fbaipublicfiles.com/glue/superglue/data/v2/MultiRC.zip"
expected = "b3cd440856e72eb166b2edcd37b798455f1ebd51f2c3de64c0c2a4e1971d2737"
with urllib.request.urlopen(url, timeout=60) as response:
    archive = response.read(2_000_001)
if len(archive) != 1_116_225 or hashlib.sha256(archive).hexdigest() != expected:
    raise ValueError("official archive size/hash changed")
(root / "MultiRC.zip").write_bytes(archive)
members = {
    "train.jsonl": (3_094_341, "bb73d0838618f8269190a2533fead3140607558975ea0df6511fa534e8d3535c"),
    "val.jsonl": (550_086, "d2b480195b15574ac00d52c4479f630bc161a7ab2de77e970fd00652846953ee"),
}
with zipfile.ZipFile(io.BytesIO(archive)) as bundle:
    for name, (size, digest) in members.items():
        member = "MultiRC/" + name
        if bundle.namelist().count(member) != 1 or bundle.getinfo(member).file_size != size:
            raise ValueError("unexpected or duplicated allowlisted member")
        with bundle.open(member) as stream:
            data = stream.read(size + 1)
        if len(data) != size or hashlib.sha256(data).hexdigest() != digest:
            raise ValueError("official JSONL bytes changed")
        (root / name).write_bytes(data)
(root / "source-lock.json").write_text(json.dumps(dict(url=url,
    expected_sha256=expected, archive_bytes=len(archive), members=members), indent=2))
PY
```

Do not extract the archive wholesale or read `test.jsonl`. Final evaluation uses
official **validation**, not the official test split.

Acquire the public Encoder through the bounded acquisition function:

```bash
"$PY" -c 'import sys; from group_encoder import acquire; acquire(sys.argv[1])' "$RUN/granite97"
```

The model is `ibm-granite/granite-embedding-97m-multilingual-r2`, revision
`835ad14087e140460703cf0fae09f97d469d65c2`. `source-lock.json` records the five
allowed files and sizes before transfer; `material.json` records their SHA256s.
Only the local verified snapshot is used after acquisition.

## Execute the source-bound stages

First prepare and meter the nonfinal shared feature bank. This stage opens only
official training data; its persisted receipt retains loading/encoding costs.

```bash
"$PY" reader_prepare.py --source "$RUN/source" --snapshot "$RUN/granite97" \
  --output "$RUN/features"
"$PY" reader_learnability.py --source "$RUN/source" --snapshot "$RUN/granite97" \
  --feature-cache "$RUN/features" --output "$RUN/gate"
```

The train-only gate uses seed 41, 1,000 updates and all 38 candidates of eight
complete training questions. Its tested result passed: F1_a 0.9565217391 and
question exact match 0.875. This establishes small-sample optimization
learnability, not generalization. The campaign checks its source and feature
bindings before opening validation; do not edit Python sources between stages.

Build the prospective native controller in a fresh isolated workspace:

```bash
"$PY" build_group_native.py --repo "$REPO" --output "$RUN/native-control" \
  --binary ndu-group-control --clippy
```

This copies the three native crates byte-for-byte, except generated minimal
manifests, and records original source hashes, generated manifests, Cargo.lock,
toolchain information and binary hash. Initial resolution generates a lock;
the actual build and strict Clippy use `--locked`. It is isolated native
qualification, not qualification of the complete repository workspace.

Run the campaign; seeds 41, 47 and 53 are fixed in the implementation:

```bash
"$PY" reader_campaign.py --source "$RUN/source" --snapshot "$RUN/granite97" \
  --feature-cache "$RUN/features" --gate "$RUN/gate" --output "$RUN/campaign" \
  --native-binary "$RUN/native-control/target/debug/ndu-group-control" --steps 512
for seed in 41 47 53; do
  "$PY" group_reader_review.py "$RUN/campaign/seed-$seed" \
    --source-dir "$RUN/source" --code-dir "$REPO/qualification/stem-cell-v1"
done
```

The frozen paragraph caps are 32 Reader training, eight tuning, eight verifier
fitting, eight critic fitting, eight critic calibration and 16 final validation
paragraphs. These source groups are disjoint. The final subset contains 747
candidates from 152 complete questions; every selected question retains every
official answer candidate. It is a fixed public-validation subset, not a test
score or the complete validation benchmark.

## Read the evidence without extending its claims

Persist `design.json`, each seed's protocol/training/critic receipts, raw
observations, trace samples, cost frontiers, report and independent review,
plus `encoder.json`, shared feature allocation and `completion.json`. The
reviewer rereads pinned official labels, checks complete candidate membership,
code bindings, metrics and actual cost sums. It does not independently attest
model execution, recompute feature values or establish preregistration time.

Compare all arms/cohorts against the persisted all-positive baseline: its F1_a
on this final subset is approximately 0.603738. Do not infer that a learned arm
beats it, or that NDU improves generalization, before inspecting the completed
raw observations and independent reviews. The objective is candidate
correctness utility, a surrogate for nonadditive question F1/EM.

Native Q32 control executes before a future proposal, with frozen observable
context and artifact hashes. Frozen learned verifier acceptance means model
agreement, not semantic truth. Critic envelopes and future cost support are
empirical, not certified. Native subprocess wall time is already inside outer
callback wall time; child CPU is reported separately and included in total
online CPU when measured. Do not add child wall a second time. Native formula
work remains unknown; complete lifecycle cost and equal-compute qualification
remain false. No production NDU owner or general stochastic FBSDE is claimed.

Local qualification evidence before final formatting: 388 Python tests passed
with actual native binaries (`reader-v3-complete-tests.log`). Isolated native
locked build and strict Clippy passed. The repository-scoped `just test
-p codex-hepta-ndu` was attempted but blocked by the sparse checkout's
missing `codex-rs/aws-auth/Cargo.toml`; see `reader-v3-repository-rust-test.log`.
That failure is not a passing full-workspace Rust gate. No tests were rerun
after final formatting; the final source-bound native build receipt records
the formatted source and compiled binary.
