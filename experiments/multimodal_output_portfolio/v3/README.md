# HEPTA NDU feedback generation v3

## What this stage actually implements

The code couples actual four-decoder Torch generation to a compiled `codex-hepta-ndu` action/budget owner. After each executed refinement it observes the current latent, matches that state to a frozen finite policy, asks the native process to select and charge STOP or REFINE, executes the chosen neural operation, and acknowledges the new state or all four emitted output hashes. The native process cannot issue another action while feedback is pending.

The generator is an artificial stochastic restoration benchmark. A source-conditioned clean anchor is subjected to mandatory external disturbances. A learned conditional contraction corrects its residual before a new disturbance arrives. The source encoders, initial map and four decoders stay frozen; only the new refiner is updated. The no-disturbance direct decoder is explicitly evaluated as a bypass reference. This is not a diffusion-model or foundation-model advantage claim.

Finite trees contain all eight conditions and all three-branch noise histories through depth three. They are evaluated offline, with every actual model forward counted. The policy is optimal for its registered finite support and objective; this enumeration grows exponentially and is not a scalable learned neural controller. New evaluation worlds provide fresh input/noise draws on the same known support, not novel semantic classes.

The separate source-evidence experiment evaluates three declared joint failure regimes. Robust direct output portfolios can hedge uncertain semantics over eight classes; they are not four-modality resource allocations. The paid witness is a new independent raw text observation; choosing it executes a restricted fallback rule that emits the witness encoder's class. Its error channel is composed with the frozen encoder's exhaustively checked 16 possible text inputs. Adding a witness changes the information set and is not a solution to the original no-new-information impossibility.

## Scope of preference and BSDE support

`preference.py` fits a single bounded risk coefficient from independent randomized Gaussian-lottery choices at fixed utility scale and logistic temperature. It reports Fisher information, boundary fits and heldout likelihood, and passes the fitted coefficient into the finite generator policy. These are synthetic preferences; they are not real-user identification or endogenous coupled preference dynamics.

`risk.py` implements rectangular finite robust Bellman recursion and a known entropic Brownian BSDE special case. The utility process U and martingale exposure Z are distinct from neural parameter gradients. No general nonlinear controlled FBSDE solver or global neural-training optimum is claimed. See THEORY.md for exact assumptions and primary sources.

## Reproduce

Use Python 3.12, NumPy 1.26.4 and Torch 2.5.1 CPU. A new native build also requires the repository's Rust toolchain. The original v2 checkpoints are required: `protocol.json` pins each SHA256. The accompanying data package has this layout relative to its extraction directory:

| Package path | Purpose |
| --- | --- |
| `native/ndu-feedback-generation` | Original compiled Linux x86-64 binary; SHA256 `f3ae369208da0bc029c5e5b829b46a92867f7a69cc1d7fbfb35a212460d05eb3` |
| `source-checkpoints/seed-17/supervised-model.pt` | Frozen v2 input checkpoint for seed 17 |
| `source-checkpoints/seed-29/supervised-model.pt` | Frozen v2 input checkpoint for seed 29 |
| `source-checkpoints/seed-43/supervised-model.pt` | Frozen v2 input checkpoint for seed 43 |
| `confirmation/` | Original v3 run data and receipts; preserve this directory as recorded evidence |

The runner checks both the native binary SHA256 and every source hash in `evidence/native_build_final.json`, including in `--smoke` mode. Full runs additionally require their source and build-receipt bytes to match the current Git commit. A newly compiled binary can differ by platform, toolchain or build path and cannot simply replace the archived binary under the original receipt.

### A. Re-execute the frozen source with the original binary

Use a separate checkout of the original implementation and a compatible Linux x86-64 host. Replace the absolute example paths below; the output directory must not already exist. `confirmation/` is the original evidence, not the destination for a new run.

```bash
git worktree add --detach /absolute/path/ndu-v3-replay \
  9653b066563df803b6f18c0045c49b9f73312c50
cd /absolute/path/ndu-v3-replay
export NDU_V3_DATA=/absolute/path/unpacked-data-package
chmod u+x "$NDU_V3_DATA/native/ndu-feedback-generation"

python experiments/multimodal_output_portfolio/v3/run.py \
  --source-run "$NDU_V3_DATA/source-checkpoints" \
  --native-binary "$NDU_V3_DATA/native/ndu-feedback-generation" \
  --output /absolute/path/new-v3-replay
```

No rebuild is needed for this route. If the archived executable cannot run on the host, use route B with a truthful new receipt. Do not disable the hash checks. Re-execution on the same registered worlds is reproduction, not new independent confirmation.

### B. Build and record a new reproduction commit

Create a separate branch/worktree from the same frozen implementation and keep runtime/protocol code unchanged. The following build step records the actual binary, environment and command; it replaces the build receipt only in that new worktree. The original receipt remains preserved at the original commit and with the original run evidence. Native source hashes must still match the original native build's source set.

```bash
git worktree add -b reproduction/ndu-v3-local /absolute/path/ndu-v3-reproduction \
  9653b066563df803b6f18c0045c49b9f73312c50
cd /absolute/path/ndu-v3-reproduction
export NDU_V3_DATA=/absolute/path/unpacked-data-package
export NDU_V3_BUILD=/absolute/path/ndu-v3-reproduction-target

python - <<'PY'
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess

repo = Path.cwd()
receipt_path = repo / 'experiments/multimodal_output_portfolio/v3/evidence/native_build_final.json'
original_bytes = receipt_path.read_bytes()
original = json.loads(original_bytes)
sha256 = lambda data: hashlib.sha256(data).hexdigest()
sources = {path: sha256((repo / path).read_bytes()) for path in original['source_sha256']}
if sources != original['source_sha256']:
    raise RuntimeError('source drift: this recipe rebuilds the original implementation')
target = Path(os.environ['NDU_V3_BUILD']).resolve()
command = ['cargo', 'build', '--locked', '-p', 'codex-hepta-ndu',
           '--bin', 'ndu-feedback-generation', '--target-dir', str(target)]
completed = subprocess.run(command, cwd=repo / 'codex-rs', check=True)
binary = target / 'debug' / ('ndu-feedback-generation.exe' if os.name == 'nt' else 'ndu-feedback-generation')
receipt = {
    'schema': 'hepta.native-reproduction-build.v3',
    'parent_recorded_build_receipt_sha256': sha256(original_bytes),
    'source_commit_before_receipt': subprocess.check_output(
        ['git', 'rev-parse', 'HEAD'], cwd=repo, text=True).strip(),
    'source_sha256': sources,
    'binary_sha256': sha256(binary.read_bytes()),
    'binary_bytes': binary.stat().st_size,
    'binary_path': str(binary),
    'system': platform.platform(),
    'rustc': subprocess.check_output(['rustc', '--version'], cwd=repo / 'codex-rs', text=True).strip(),
    'command': command,
    'working_directory': str(repo / 'codex-rs'),
    'exit_code': completed.returncode,
    'tests_executed_by_this_build_step': False,
}
receipt_path.write_text(json.dumps(receipt, indent=2) + '\n')
PY

git add experiments/multimodal_output_portfolio/v3/evidence/native_build_final.json
git commit -m "Record native build receipt for local v3 reproduction"

python experiments/multimodal_output_portfolio/v3/run.py \
  --source-run "$NDU_V3_DATA/source-checkpoints" \
  --native-binary "$NDU_V3_BUILD/debug/ndu-feedback-generation" \
  --output /absolute/path/new-v3-reproduction
```

Use the `.exe` suffix for the final binary argument on Windows. Preserve the new commit, receipt and output directory together. The runner records that new commit and validates its committed source bytes; it does not relabel it as the original confirmation. This recipe records a build, not new test results or a production attestation. `--smoke` uses development draws and shorter schedules; it is never confirmatory and still requires the matching binary/build receipt.

The existing test suites can be run separately. Use the repository wrapper for Rust tests:

```bash
PYTHONPATH=experiments/multimodal_output_portfolio:experiments/multimodal_output_portfolio/v3 \
  python -m unittest discover -s experiments/multimodal_output_portfolio/v3 -p 'test_*.py'
cd codex-rs
just test --locked -p codex-hepta-ndu
```

## Evidence and interpretation

The original preregistration is commit `6ab6aa4107b33917580cc041bc36b6603dad8aaa`. The first confirmation implementation freeze is `9653b066563df803b6f18c0045c49b9f73312c50`. Implementation clarifications were recorded before confirmation; scientific thresholds, seeds and disturbance laws were not tuned after heldout inspection.

Primary endpoint: mean external loss of NDU feedback minus the same NDU generator with one fixed depth, under nominal noise. The registered minimum reduction is 0.01, paired CI upper bound must be negative, ideal online Linear MAC ratio must be at most 1.10, all outputs/budgets must pass, and all three seeds must run. Additional mechanisms require nondegenerate refinement, actual current-latent-dependent actions and direct utility-only refiner gradients.

Other contrasts are descriptive and unadjusted. A feedback-versus-static gain does not by itself prove an NDU-training advantage, continuation advantage over myopic control, robust-shift superiority or a preference benefit. All these comparisons are reported separately. Dense Linear MACs exclude nonlinear arithmetic, backward/optimizer work and control/IPC work. Native process lifetime and request round trips are reported separately; lifetime includes waiting for Python training and generation.

v1/v1.1/v2 files and negative results remain unchanged. Development001 failed at NumPy boolean JSON serialization after its actual model/native loops; the failed directory is retained. Development002 completed. Final results and blocker ledger are published alongside the independent review.
