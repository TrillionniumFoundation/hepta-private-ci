# Code-only historical Library recovery (2026-11-03)

Scope: TWO exact standalone, original ChatGPT Library Python sources, preserved under `source/`. No operational files or production modules are replaced.

| Source | Original SHA-256 | Original Git blob SHA-1 |
|---|---|---|
| `encoder_meter.py` | `806b5b1b369b80f9a62faef627b17764810d6fa2f095654b3463abff645bd78e` | `db9f74fd6b3a8b3ae83e634d4a089a060fc0ff98` |
| `audit_hepta_diverse60.py` | `25fd4363c31e2183dcb5c8d169629cdd27da64238d0741c594c1922584d0d1d5` | `fa9d46643ff8d507ee465306f04363629bad40e6` |

## Reproduce source identity

From this directory:

```sh
sha256sum source/encoder_meter.py source/audit_hepta_diverse60.py
git hash-object source/encoder_meter.py source/audit_hepta_diverse60.py
python -m py_compile source/encoder_meter.py source/audit_hepta_diverse60.py test_encoder_meter_smoke.py
```

Compare hashes with the table above. Python standard-library compilation checks both sources; this is **not** an integration test.

## Reproduce bounded meter smoke

Requires Python 3.10+ and PyTorch 2.x. No datasets, weights, network access or GPUs required.

```sh
python -m unittest -v test_encoder_meter_smoke.py
```

The three assertions cover exact forward/row/token-slot counts, failure remaining incomplete, rejection of rank-1 input, cleanup of hooks, and explicit `BLOCKED` production admission. Local isolated verification on CPU/PyTorch 2.10.0 reported **3/3 PASS** on 2026-11-03. This does not prove worker sharing, kernel execution, signatures, or production readiness.

## Independent diverse60 audit prerequisites and limitations

The original audit source expects `hepta-diverse60-94904213-original.zip` alongside itself. It enforces archive SHA-256 `8a602cd2a6f0cdaf3833479f838fb792f55a35882894356a810469916e7a05fe` and internal manifest/payload checks. The original archive has **not** been included in this code-only recovery; therefore its full audit is **NOT EXECUTED/NOT QUALIFIED** in this PR.

Only when the original artifact is separately and lawfully available, copy it into `source/`, verify its SHA-256 first, and then run:

```sh
(cd source && python audit_hepta_diverse60.py)
```

The script will write a local `hepta-diverse60-independent-audit.json`; do not mistake it for fresh independently executed training/verification. No full untrusted-archive OS isolation is provided by this historical source.

## Safety status

`DENY_ALL`: source preservation only. Does not assert successful historical reproduction, NDU benefit, cryptographic authority, model release permission, or any production gate. Do not merge to protected main until normal independent review/CI. Library deletion remains forbidden pending *all* Library file/archive comparisons and original dot-host worktree/remote reconciliation. No Gmail addresses or credential material are intentionally included.
