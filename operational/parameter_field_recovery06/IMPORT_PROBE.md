# Execution06 import and registration probe

`import_probe.py` is the explicit execution06 successor of the frozen execution04 probe. Run it only after the new registration and the literal A17 import exist, using the registered interpreter from the registered empty directory. It does not start the supervisor or a scientific worker.

The CLI retains the original policy, freeze and output arguments and adds an externally pinned registration configuration:

```text
<registered-python> -B <source-root>/operational/parameter_field_recovery06/import_probe.py
  --policy <ops-root>/registrations/initial/CWD_POLICY.json
  --expected-policy-sha256 <actual-policy-sha256>
  --freeze <ops-root>/registrations/initial/A_SOURCE_FREEZE.json
  --expected-freeze-sha256 <actual-A-freeze-sha256>
  --registration-config <ops-root>/registrations/initial/REGISTRATION_CONFIG.json
  --expected-registration-config-sha256 <actual-registration-config-sha256>
  --output <ops-root>/import_probe/IMPORT_CLOSURE.json
```

All seven values are required. The caller must supply actual frozen hashes; there is no test mode in the production CLI. The selected freeze may be the exact A, C or controller freeze in the registration configuration. A is the suggested initial source closure.

## Checks and boundaries

The original 768 MiB reservation plus 1 GiB memory margin gate runs before scientific module imports. The probe imports the original scientific modules and pinned HCSN class modules, checks the exact restored Python/Torch/NumPy/Pillow versions, and runs the original loaded-source closure check. It does not instantiate a model, decode a checkpoint tensor, read dataset values, call a scientific entrypoint, or run a controller loop.

The probe constructs all eight real `ProducerAdapter` factories inside the installed resource adapter. It verifies the controller and private clones retained the installed resource aliases and checks restoration afterwards. The initial A29/A43/C freeze gates, controller envelope validation, initial four-job metadata, original A17 profile, registration configuration, historical cost plan, 32 execution04 root WAIT4 records and 96 support descriptors are checked without scientific evaluation. The A/C closure is frozen before producer metadata and policy; the later OPS freeze must bind the exact policy and producer descriptor.

The imported RAW file identities must remain identical before and after the probe. The registered cwd must remain empty. The receipt and a separate sibling `<receipt-stem>_BACKPRESSURE` directory are written outside RAW, source, and the supervisor's fixed wrapper/resource token populations. The probe has its own bounded 300 second import-only deadline and records its actual OOM baseline. It must precede `START_POLICY.json`; the subsequent supervisor independently owns the unchanged 12 hour execution deadline.

A successful probe is an import and metadata closure result. It does not establish that the scientific run has passed its resource qualification or completed its endpoints.

## Validation scope

`validation/import_probe/VALIDATION.json` records a real wait4 measurement of 12 low-memory tests. The tests construct all eight real source-pinned factories with an explicitly unvalidated fixture owner, check the installed aliases, and exercise the complete probe control flow with synthetic scientific imports. They also cover original admission rejection, OOM changes, runtime mismatch, missing policy binding, C closure mismatch, stale controller aliases, RAW mutation, protected output populations and the 32/96 history population. They import neither Torch nor NumPy and create no actual execution06 RAW or OPS.

The read-only integration audit additionally exercised the actual root `execution04_costs.build_cost_facts` and historical cost validator against restored real execution04 receipts. Only the import metadata binding and output directory in that audit were explicit temporary fixtures; this was not a materialized or accepted A17 import. Actual initialization and this production probe remain separate required steps.
