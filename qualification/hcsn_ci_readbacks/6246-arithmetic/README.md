# Read-only retained arithmetic CI originals for #6246

This preserves the existing successful [run43211637802 / job131160452291](https://github.com/TrillionniumFoundation/hepta-private-ci/actions/runs/43211637802/job/131160452291) at exact source `e76e9dbccecbb7fa4cae4cacdd05b116f6ec6546`.

The original artifact13941387328 is188380B, SHA256 `4cd532648c72f6caaf6cde87a1941a739fe7268706b6688d616f48f47cbe060d`. It contains12 members, all passing the restored root executor's CRC check. The full ZIP, complete decoded job log, original CI/review/admission/source-map/stdout/stderr records, member index and API metadata are retained. Inputs inside the ZIP retain their exact bytes.

The actual CI reruns the independent retained-array arithmetic inspector only:345 scalar comparisons, zero failures;16 source/input/workflow files agree before/after. The raw CI receipt equals its complete-log record, and the original REVIEW hash agrees with both. The existing CI and this archiver each execute zero candidate imports, adjoints, forward DDEs, matrix exponentials, static solves, Torch calls or optimizer updates. The existing inspector reports0.283770312s wall /0.172401627s CPU; these are arithmetic-review costs, excluding full hosted setup. Original18 adjoint/196 exponential/two static-solve stage costs remain separate in REVIEW.json.

Earlier RED run43210615842/job131156949772 is preserved in the source head. It failed before the inspector because its review-package FORMAT copy had exactly one extra final LF relative to the canonical798-byte FORMAT. The current workflow checks precisely `canonical + b'\n'`, keeping both originals intact.

No source head/workflow/original was changed and no workflow/native/numerical job was restarted. All additions are under `qualification/hcsn_ci_readbacks/6246-arithmetic`, outside candidate workflow path filters. No formatter is applied to retained original bytes. HOLD_NO_GO remains; this readback adds no adaptive-program reverse, Torch adapter, large-grid, broad-domain or production qualification.
