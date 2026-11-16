# MIC experiment ownership and admission regression

The original native run at `577c03b5524fd45814dc71c3b5d847562ba2c410`
disproved `mic_labels_preserve_original_outside_and_protected_child_oracles`.
Its raw JUnit failure and all five mechanism observations remain unchanged in
`windows-acl-577c/native-tests-original.zip` (SHA-256
`f5adf8f324f6398b73a3c6b5cfeced1598f278b7c1257809f6d67431be0c9bd5`).

That test constructs a private `WRITE_RESTRICTED` diagnostic token and measures
owned temporary objects. It never exercised production admission. It therefore
owned an experimental preservation hypothesis, not evidence that the production
backend had attained the required deletion isolation. Production legacy and
elevated admission remain closed.

## Explicit regression contract

The replacement method is
`token::tests::mic_probe::mic_counterexamples_require_public_admission_refusal`.
It retains every original mechanism operation, label/DACL audit, physical
readback, control assertion, cleanup, and the unchanged `original_oracle`
predicate. All five evaluations are recorded; their result remains `false`.

| Case                           | Native observation retained                    | Original isolation hypothesis |
| ------------------------------ | ---------------------------------------------- | ----------------------------- |
| 0: ordinary token              | Outside and protected-child deletion succeeds  | FAIL                          |
| 1: low token only              | Intended writable-root mutation is also denied | FAIL                          |
| 2: prepared low writable roots | Protected `.git` is deleted through its parent | FAIL                          |
| 3: low outside root            | Outside and protected-child deletion succeeds  | FAIL                          |
| 4: explicit target DELETE deny | Parent deletion still removes protected `.git` | FAIL                          |

Before the private token runs, both real public capture APIs must refuse the
same prepared two-root workspace-write request with their exact typed isolation
errors. After each refusal, entry/content/DACL snapshots, every mandatory label,
the absent child marker, and the absent provisioning home must match. This adds
ten actual public admission checks. The mechanism comparison also requires the
complete observed success/denial/error-code matrix and physical postconditions;
an unrelated failure cannot pass by making `original_oracle` false.

## CI and evidence meaning

The native observation workflow still executes all 17 reviewed ACL/token
methods, the existing three elevated admission methods, and the existing six
probe collector methods without skips or retries. It adds seven adversarial
MIC collector tests and captures successful-test output once. The collector
requires five exact observations plus their public refusal evidence and writes
`mic-counterexample-observation.json` with both:

- `regression_status: PASS`, meaning counterexample and refusal checks passed;
- `original_isolation_hypothesis: FAIL` and `permission_qualification: false`.

The existing full-CI functional tests, including the elevated four-cell deletion
oracle, are unchanged and remain required. This change does not establish that
elevated child launch, IPC, reads, or permitted writes work, and does not reopen
either production backend. A refusal regression cannot satisfy those functional
qualification requirements.

Local collector tests, Ruff, YAML/source-pin checks, and a native Rust 1.96
formatter check are available for this patch. Native Windows execution of the
new coupled method is pending publication; no Windows PASS is claimed here.
