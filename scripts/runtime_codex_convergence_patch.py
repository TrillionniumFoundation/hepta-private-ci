#!/usr/bin/env python3
"""One-shot exact-text convergence transform; removed from the published candidate."""
from pathlib import Path
root = Path.cwd()
def edit(path, old, new):
    p = root / path
    source = p.read_text()
    if source.count(old) != 1:
        raise RuntimeError((path, source.count(old), old[:120]))
    p.write_text(source.replace(old, new))

p = 'codex-rs/hepta-agentd/src/lane_b_runtime.rs'
edit(p, '''        record.dispatch_digest = dispatch_digest.map(str::to_string);
        record.phase = RunPhase::Dispatched;
        advance_revision(record)?;''', '''        let revision = record.revision.checked_add(1)
            .ok_or(AgentRunError::ArithmeticOverflow)?;
        record.dispatch_digest = dispatch_digest.map(str::to_string);
        record.phase = RunPhase::Dispatched;
        record.revision = revision;''')
edit(p, '''        record.dispatch_digest = Some(dispatch_digest.to_string());
        // Precompute before changing state; overflow must leave the owner unchanged.''', '''        // Precompute before changing state; overflow must leave the owner unchanged.''')
edit(p, '''        record.phase = RunPhase::Cancelled;
        record.abort_origin_revision = Some(pre_dispatch_revision);''', '''        record.dispatch_digest = Some(dispatch_digest.to_string());
        record.phase = RunPhase::Cancelled;
        record.abort_origin_revision = Some(pre_dispatch_revision);''')
p = 'codex-rs/hepta-agentd/src/lane_b_runtime_tests.rs'
with (root / p).open('a') as stream:
    stream.write('\n#[path = "runtime_codex_convergence_tests.rs"]\nmod convergence_tests;\n')
p = 'codex-rs/hepta-infer-worker-host/src/runtime_codex_attempt.rs'
edit(p, '''        self.owner_revision = Some(owner_revision);
        Ok(self.transition())''', '''        self.owner_revision = Some(owner_revision);
        self.effect_may_have_happened = true;
        Ok(self.transition())''')
edit(p, '''impl Attempt<OwnerCommitted> {
    pub fn abort_before_effect(''', '''impl Attempt<DurablePrepared> {
    pub fn abort_before_effect(''')
edit(p, '''    #[must_use]
    pub fn enter_effect(mut self) -> Attempt<EffectEntered> {''', '''}

impl Attempt<OwnerCommitted> {
    #[must_use]
    pub fn enter_effect(mut self) -> Attempt<EffectEntered> {''')
edit(p, 'assert!(!attempt.effect_may_have_happened());', 'assert!(attempt.effect_may_have_happened());')
edit(p, '''            .commit_owner(2, dispatch)
            .unwrap()
            .abort_before_effect''', '''            .abort_before_effect''')
edit(p, 'method after `enter_effect`: once effect entry is possible, recovery is', 'method after `commit_owner`: once the owner fence commits, recovery is')
p = 'codex-rs/hepta-infer-worker-host/src/native_execution.rs'
edit(p, 'let mut owner_abort_required = intelligence.is_some();', 'let owner_abort_required = intelligence.is_some();')
edit(p, 'let send_budget = execution_clock.remaining(unix_time_ms()?)?.min(RPC_TIMEOUT);', 'execution_clock.remaining(unix_time_ms()?)?;')
edit(p, '''                if dispatched.phase != AgentRunPhase::Dispatched
''', '''                if dispatched.run_id != binding.run_id
                    || dispatched.revision != binding.expected_revision.checked_add(1)
                        .ok_or("Agentd effect-entry revision overflow")?
                    || dispatched.phase != AgentRunPhase::Dispatched
''')
edit(p, '''            Ok((entered_use, send_budget))''', '''            // An owner RPC can consume the entire remaining budget. Once that
            // fence may have committed, expiry/cancellation retains the slot;
            // neither is permission to abort the owner or send with old time.
            if cancellation.is_cancelled() {
                return Err("cancelled after final-use checks; no model send".into());
            }
            let send_budget = execution_clock.remaining(unix_time_ms()?)?.min(RPC_TIMEOUT);
            Ok((entered_use, send_budget))''')
edit(p, '''                            control.complete_native_rejection_before_start(request_id)?;
                        }
                        thread_guard.cleanup().await;''', '''                            control.complete_native_rejection_before_start(request_id)?;
                        }
                        // A definitive rejection is safe to clean up only after
                        // both owners have durably acknowledged it.
                        thread_guard.terminal_persisted();
                        thread_guard.cleanup().await;''')
p = 'codex-rs/hepta-infer-worker-host/src/native_run_control.rs'
edit(p, '''        let binding = record
            .owner_dispatch
            .as_ref()
            .ok_or("pending runtime.codex rejection omitted its Agentd owner binding")?;''', '''        let Some(binding) = record.owner_dispatch.as_ref() else {
            control.complete_native_rejection_before_start(&record.request.request_id)?;
            return Ok(());
        };''')
p = 'codex-rs/hepta-infer-worker-host/src/final_use_authorizer.rs'
edit(p, '                peer.pid(),', '                peer.pid().map(u32::try_from).transpose()?,')
p = 'codex-rs/hepta-infer-worker-host/src/native_deadline.rs'
edit(p, '        let milliseconds = u64::try_from(budget.as_millis())?;', '''        let milliseconds = u64::try_from(budget.as_millis())?;
        if milliseconds == 0 {
            return Err("native deadline budget must be at least one millisecond".into());
        }''')
p = '.github/workflows/runtime-codex-qualification.yml'
edit(p, '          echo "HEPTA_CI_TESTED_SHA=$(git rev-parse HEAD)" >> "$GITHUB_ENV"', '''          echo "HEPTA_CI_TESTED_SHA=$(git rev-parse HEAD)" >> "$GITHUB_ENV"
          echo "TESTED_SHA=$(git rev-parse HEAD)" >> "$GITHUB_ENV"
          echo "SOURCE_SHA=$SOURCE_SHA" >> "$GITHUB_ENV"
          echo "BASE_SHA=$BASE_SHA" >> "$GITHUB_ENV"''')
edit(p, '  workflow_dispatch:\n', '''  workflow_dispatch:
  workflow_call:
    inputs:
      source_sha:
        type: string
        required: true
      base_sha:
        type: string
        required: true
''')
edit(p, '    runs-on: ubuntu-24.04-arm\n', '    permissions:\n      contents: read\n    runs-on: ubuntu-24.04-arm\n')
edit(p, '      SOURCE_SHA: ${{ github.event.pull_request.head.sha || github.sha }}', '      SOURCE_SHA: ${{ inputs.source_sha || github.event.pull_request.head.sha || github.sha }}')
edit(p, '      BASE_SHA: ${{ github.event.pull_request.base.sha || github.event.before }}', '      BASE_SHA: ${{ inputs.base_sha || github.event.pull_request.base.sha || github.event.before }}')
edit(p, '      CARGO_INCREMENTAL: 0', '''      CARGO_INCREMENTAL: 0
      CARGO_BUILD_JOBS: 4
      CARGO_PROFILE_DEV_DEBUG: 0
      CARGO_PROFILE_TEST_DEBUG: 0''')
edit(p, 'run: python3 -m unittest -v scripts.tests.test_runtime_codex_receipt_v2', 'run: python3 -m unittest -v scripts.tests.test_runtime_codex_receipt_v2 scripts.tests.test_runtime_codex_target_host_evidence scripts.tests.test_runtime_codex_convergence')
edit(p, "    if: ${{ always() && (github.event_name != 'pull_request' || github.event.pull_request.head.repo.full_name == github.repository) }}", "    if: ${{ always() && inputs.source_sha == '' && (github.event_name != 'pull_request' || github.event.pull_request.head.repo.full_name == github.repository) }}")
p = '.github/workflows/blocking-ci.yml'
edit(p, '  required:\n', '''  runtime-codex:
    name: runtime.codex mandatory source lanes
    uses: ./.github/workflows/runtime-codex-qualification.yml
    permissions:
      contents: read
      actions: read
      id-token: write
      attestations: write
    with:
      source_sha: ${{ github.event.pull_request.head.sha || github.sha }}
      base_sha: ${{ github.event.pull_request.base.sha || github.event.before }}

  required:
''')
edit(p, '      - lightweight\n', '      - lightweight\n      - runtime-codex\n')
p = 'scripts/runtime_codex_receipt_v2.py'
edit(p, '    run.add_argument("--records", type=Path, required=True)', '''    run.add_argument("--records", type=Path, required=True)
    run.add_argument("--suite", choices=tuple(PLAN))''')
edit(p, '''        for name, (floor, command) in PLAN.items():
            result''', '''        for name, (floor, command) in PLAN.items():
            if args.suite and name != args.suite:
                continue
            result''')
p = 'scripts/runtime_codex_target_host_evidence.py'
edit(p, 'json.dumps(value, sort_keys=True, separators=(",", ":"))', 'json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)')
edit(p, '''    try:
        value = json.loads(path.read_text(encoding="utf-8"))''', '''    if path.is_symlink() or not path.is_file() or path.stat().st_size > 2 * 1024 * 1024:
        raise EvidenceError("unsafe or oversized JSON evidence")
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise EvidenceError("duplicate JSON key")
            result[key] = value
        return result
    def nonfinite(_):
        raise EvidenceError("nonfinite JSON evidence")
    try:
        value = json.loads(path.read_text(encoding="utf-8"),
                           object_pairs_hook=unique, parse_constant=nonfinite)''')
edit(p, 'if any(number < 0 for number in numbers):', 'if any(not math.isfinite(number) or number < 0 for number in numbers):')
edit(p, 'if not isinstance(value, str) or not pattern.fullmatch(value):', 'if not isinstance(value, str) or not pattern.fullmatch(value) or set(value) == {"0"}:')
edit(p, '    if args.iterations < 30 or args.iterations > 200:', '    if type(args.iterations) is not int or args.iterations < 30 or args.iterations > 200:')
edit(p, '    if args.generation <= 0:', '    if type(args.generation) is not int or args.generation <= 0:')
edit(p, '''    if value.get("physicalRequestCount") != expected_requests:
        raise EvidenceError("provider audit did not prove exactly one send per canary")''', '''    if type(value.get("physicalRequestCount")) is not int or value["physicalRequestCount"] != expected_requests:
        raise EvidenceError("provider audit did not prove exactly one send per canary")''')
edit(p, '''    if value.get("duplicateRequestCount") != 0:
        raise EvidenceError("provider audit observed duplicate requests")''', '''    if type(value.get("duplicateRequestCount")) is not int or value["duplicateRequestCount"] != 0:
        raise EvidenceError("provider audit observed duplicate requests")''')
edit(p, '''    expected_requests = 0 if scenario in ZERO_SEND_FAULTS else 1
    if value''', '''    expected_requests = 0 if scenario in ZERO_SEND_FAULTS else 1
    for field in ("physicalRequestCount", "freshFenceAckCount", "duplicateRequestCount", "replayedRequestCount"):
        if type(value.get(field)) is not int or value[field] < 0:
            raise EvidenceError(f"invalid integer count: {field}")
    if value''')
edit(p, '''            if not path.is_file():
                raise EvidenceError(f"missing target-host run evidence: {path}")''', '''            if path.is_symlink() or not path.is_file() or path.stat().st_size > 128 * 1024 * 1024:
                raise EvidenceError(f"missing, unsafe or oversized target-host run evidence: {path}")''')
edit(p, '''        "minimumStatisticalSampleMet": args.iterations >= 30,''', '''        "minimumCollectionSampleMet": args.iterations >= 30,
        "percentileInterpretation": "empirical interpolation; not a population p99 confidence guarantee",
        "authenticity": "not-verified",
        "evidenceRootLayout": "manifest-parent",''')
edit(p, '''            "realProviderCanariesExecuted": True,
            "faultMatrixExecuted": True,''', '''            "realProviderCanariesExecuted": False,
            "faultMatrixExecuted": False,
            "submittedCanaryRecordsComplete": True,
            "submittedFaultRecordsComplete": True,''')
edit(p, '''    raw = path.read_bytes()
    value = json.loads(raw)''', '''    value = load_json(path)
    raw = path.read_bytes()''')
edit(p, '''    if expected != actual:
        raise EvidenceError("manifest digest sidecar mismatch")''', '''    if expected != actual:
        raise EvidenceError("manifest digest sidecar mismatch")
    # Recompute retained raw files. Re-sealed summary fields cannot fabricate
    # valid integrity; this routine still does not authenticate the producer.
    args = argparse.Namespace(evidence_root=path.parent,
        source_sha=value["sourceSha"], source_tree=value["sourceTree"],
        agent_id=value["agentId"], generation=value["agentGeneration"],
        model=value["model"], iterations=value["iterations"])
    rebuilt = build_manifest(args)
    rebuilt["host"] = value["host"]
    rebuilt["generatedAt"] = value["generatedAt"]
    if value != rebuilt:
        raise EvidenceError("manifest does not match recomputed raw evidence")''')
edit(p, '''    manifest = build_manifest(args)
    encoded''', '''    if args.output.parent.resolve() != args.evidence_root.resolve():
        raise EvidenceError("manifest must be stored beside its retained raw evidence")
    manifest = build_manifest(args)
    encoded''')
p = 'scripts/tests/test_runtime_codex_target_host_evidence.py'
edit(p, 'manifest["minimumStatisticalSampleMet"]', 'manifest["minimumCollectionSampleMet"]')
edit(p, 'self.assertTrue(manifest["claimBoundary"]["faultMatrixExecuted"])', '''self.assertFalse(manifest["claimBoundary"]["faultMatrixExecuted"])
            self.assertTrue(manifest["claimBoundary"]["submittedFaultRecordsComplete"])
            self.assertEqual(manifest["authenticity"], "not-verified")
            altered = dict(manifest)
            altered["latencySeconds"] = dict(manifest["latencySeconds"], p99=0)
            encoded = module.canonical_bytes(altered)
            args.output.write_bytes(encoded)
            args.output.with_suffix(".json.sha256").write_text(
                module.hashlib.sha256(encoded).hexdigest() + "  manifest.json\\n")
            with self.assertRaises(module.EvidenceError):
                module.verify_manifest(args.output)
            module.write_manifest(args)''')
p = '.github/workflows/runtime-codex-target-host.yml'
edit(p, '  id-token: write\n  attestations: write\n', '')
edit(p, '  target-host:\n', '''  target-host:
    if: ${{ github.ref == 'refs/heads/main' && inputs.source_sha == github.sha }}
    environment: runtime-codex-qualification
''')
edit(p, '      - name: Retain target-host evidence\n', '      - name: Retain target-host evidence\n        if: always()\n')
edit(p, '          path: .hepta-evidence/runtime-codex/target-host/', '          path: ${{ runner.temp }}/runtime-codex-target-host/')
source = (root / p).read_text()
start = source.index('      - name: Attest target-host manifest provenance')
source = source[:start] + '''  attest-target:
    if: ${{ always() && needs.target-host.result == 'success' }}
    needs: target-host
    runs-on: ubuntu-24.04
    timeout-minutes: 10
    permissions:
      contents: read
      actions: read
      id-token: write
      attestations: write
    steps:
      - uses: actions/download-artifact@3e5f45b2cfb9172054b4087a40e8e0b5a5461e7c
        with:
          name: runtime-codex-target-host-${{ inputs.source_sha }}-${{ github.run_id }}
          path: evidence
      - uses: actions/attest-build-provenance@4d101475d8b20a2381f78447822ac1eab6504dd8
        id: attest
        with:
          subject-path: evidence/manifest.json
      - uses: actions/upload-artifact@bbbca2ddaa5d8feaa63e36b76fdaad77386f024f
        with:
          name: runtime-codex-target-signature-${{ github.run_id }}
          path: ${{ steps.attest.outputs.bundle-path }}
          if-no-files-found: error
'''
(root / p).write_text(source)
edit(p, '          mkdir -p .hepta-evidence/runtime-codex/target-host\n          cp -R "${EVIDENCE}/." .hepta-evidence/runtime-codex/target-host/\n', '')
for name in ('runtime-codex-ci-closure-bootstrap.yml', 'runtime-codex-consolidate.yml', 'runtime-codex-effect-fence-bootstrap.yml', 'runtime-codex-convergence-snapshot.yml', 'runtime-codex-convergence-materialize.yml'):
    (root / '.github/workflows' / name).unlink(missing_ok=True)
Path(__file__).unlink()
print('runtime.codex bounded convergence changes materialized; qualification not inferred')
