"""Attack concrete evaluated NoUpdate continuation and fresh Root proof reads.

These are source boundary checks. They do not qualify an ordinary launcher,
daemon/Root cold recovery, or a successful learning improvement.
"""

from dataclasses import replace
import importlib.util
from pathlib import Path
import re
import sys
import tempfile
import tomllib
import unittest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location('evaluated_candidate_source_proof', ROOT / 'scripts/verify_hepta_callers.py')
assert SPEC is not None and SPEC.loader is not None
PROOF = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = PROOF
SPEC.loader.exec_module(PROOF)
AGENT = 'codex-rs/hepta-agentd/src/'
MAIN = AGENT + 'cell_q24_candidate_stage_retention.rs'
AUTH = AGENT + 'cell_q24_candidate_stage_retention_auth.rs'
BINDING = AGENT + 'cell_q24_candidate_stage_retention_binding.rs'
CHANNELS = AGENT + 'cell_q24_candidate_stage_channels.rs'
S = AGENT + 'cell_q24_candidate_stage_retention_selection.rs'
C = AGENT + 'cell_q24_candidate_stage_retention_next_use.rs'
BATCH = AGENT + 'cell_q24_candidate_stage_retention_attestations.rs'
OWNERS = AGENT + 'cell_q24_candidate_stage_owners.rs'
INPUTS = AGENT + 'cell_q24_candidate_stage_inputs.rs'
STATE = AGENT + 'cell_q24_no_update_stage_state.rs'
STAGES = AGENT + 'authority_host_learning_resident_stages.rs'
ROOT_AUTH = AGENT + 'authority_host_learning_resident_auth.rs'
EVALUATION = AGENT + 'cell_q24_candidate_stage_evaluation.rs'
PRODUCT = (MAIN, AUTH, BINDING, CHANNELS, S, C, BATCH, OWNERS, INPUTS, STATE, STAGES, ROOT_AUTH, EVALUATION)
NEW = (MAIN, AUTH, BINDING, CHANNELS, S, C, BATCH, EVALUATION)
EXPECTED = {
    'learning_original_candidate_evaluated_stage_admission': (STAGES,),
    'learning_original_candidate_evaluated_attestations': (STAGES,),
    'root_resident_concrete_evaluated_attestations': (ROOT_AUTH,),
    'learning_original_candidate_evaluated_execute': (OWNERS,),
    'learning_original_candidate_evaluated_recovery': (OWNERS,),
    'learning_original_candidate_evaluated_selection': (MAIN, BATCH),
    'learning_original_candidate_evaluated_next_use': (MAIN, BATCH),
    'learning_original_candidate_evaluated_channels': (BINDING,),
    'learning_original_candidate_evaluation_postread': (MAIN,),
}


def span(source, name):
    code = PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code(source))
    found = list(re.finditer(r'\bfn\s+' + re.escape(name) + r'(?:<[^>]*>)?\s*\(', code))
    if len(found) != 1:
        raise PROOF.VerificationFailure('unique live function: ' + name)
    start = found[0].start()
    end = PROOF._rust_item_end(code, start)
    if end is None:
        raise PROOF.VerificationFailure('complete live function: ' + name)
    return code, start, end + 1


def locate(body, marker, ordinal=0):
    pattern = r'\s*'.join(re.escape(t) for t in re.findall(r'\w+|[^\w\s]', marker))
    found = list(re.finditer(pattern, body))
    if len(found) <= ordinal:
        pattern = pattern.replace(r'\)', r'(?:,\s*)?\)')
        found = list(re.finditer(pattern, body))
    if len(found) <= ordinal:
        raise AssertionError(('actual marker', marker, ordinal))
    return found[ordinal]


def require_execute_dominance(path, source):
    """Effects must execute directly inside the actual fresh Action branch.

    A never-called closure, extra nested branch, or a Readback condition cannot
    retain the required text while moving the actual effect out of this branch.
    """
    if path not in (S, C):
        return
    name = 'original_evaluated_selection' if path == S else 'original_evaluated_next_use'
    code, start, end = span(source, name)
    body = code[start:end]
    branches = []
    for found in re.finditer(r'\bif\s+action\s*==\s*Action::Execute\s*\{', body):
        opening = body.index('{', found.start())
        closing = PROOF._rust_item_end(body, found.start())
        if closing is None:
            raise PROOF.VerificationFailure('complete Execute branch')
        branches.append((opening, closing))
    effects = [
        (r'RootResidentLearningEffectGateV3::require_current\s*\(', 3),
    ]
    if path == S:
        effects += [(r'OriginalCircuitEvaluatedSelectionCommandClientV1::execute_selection\s*\(', 1),
                    (r'\.prepare_evaluated_version\s*\(', 1)]
    else:
        effects += [(r'OriginalCircuitEvaluatedNextUseCommandClientV1::attest_completed_task\s*\(', 1),
                    (r'\.ensure_readiness\s*\(', 1), (r'\.await_evaluated_c\s*\(', 1)]
    for pattern, count in effects:
        actual = list(re.finditer(pattern, body))
        if len(actual) != count:
            raise PROOF.VerificationFailure('exact actual effect dispatch count')
        for call in actual:
            enclosing = [(a,b) for a,b in branches if a < call.start() < b]
            if len(enclosing) != 1:
                raise PROOF.VerificationFailure('effect must be dominated by actual Execute')
            opening, _ = enclosing[0]
            prefix = body[opening:call.start()]
            if prefix.count('{') - prefix.count('}') != 1:
                raise PROOF.VerificationFailure('actual effect cannot be in an unused nested body')


def require_readonly_and_mounts(path, source):
    readonly = {
        MAIN: ('read_original_evaluated_retention', 'evaluated_retention_attestation'),
        BATCH: ('read_original_evaluated_attestations', 'evaluated_predecessor_signatures'),
        S: ('read_evaluated_version',),
    }
    for name in readonly.get(path, ()):
        code, start, end = span(source, name)
        body = code[start:end]
        if re.search(r'Action::Execute|::require_current\s*\(|::execute_selection\s*\(|::attest_completed_task\s*\(|::prepare_original_version\s*\(', body):
            raise PROOF.VerificationFailure('cold read cannot ask for a future gate or execute')
    if path == OWNERS:
        code = PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code(source))
        if 'pub(super) mod retention;' not in code:
            raise PROOF.VerificationFailure('actual production retention module is required')
    if path == STATE:
        code = PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code(source))
        if 'mod evaluated_channels;' not in code:
            raise PROOF.VerificationFailure('actual production channel transfer is required')


def require_progress_and_postread_contract(path, source):
    """Only actual original reads complete a Current proof in this invocation."""
    code = PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code(source))
    if path == S:
        _, start, end = span(source, 'prepare_evaluated_version')
        body = code[start:end]
        if len(re.findall(r'OriginalCircuitRetainedVersionClientV1::prepare_original_version\s*\(', body)) != 1:
            raise PROOF.VerificationFailure('exactly one original Prepare; progress cannot retry it')
        if len(re.findall(r'OriginalCircuitRetainedVersionClientV1::publication_progress\s*\(', body)) != 1:
            raise PROOF.VerificationFailure('only one actual progress exchange per loop iteration')
        if len(re.findall(r'\.read_evaluated_version\s*\(\s*lane\s*\)', body)) != 1:
            raise PROOF.VerificationFailure('Available must consume actual complete readback')
    if path == EVALUATION:
        actual = set(re.findall(r'\bfn (\w+)\(', code))
        expected = {'new', 'into_parts', 'training_prefix', 'execute_original_evaluation',
                    'read_original_evaluation', 'read_original_evaluation_with_originals',
                    'original_evaluation', 'verify_original_evaluation', 'evaluation_failure'}
        if actual != expected or len(re.findall(r'\bPostEvaluationOriginals\b', code)) != 5:
            raise PROOF.VerificationFailure('post-read values have one private producer and no extra factory/cache')
        _, start, end = span(source, 'original_evaluation')
        body = code[start:end]
        if len(re.findall(r'common\.read_prefix\s*\(', body)) != 2:
            raise PROOF.VerificationFailure('both original common reads remain')
        if len(re.findall(r'OriginalCellQ24CandidateStageOwnersV1::read_original_candidate\s*\(', body)) != 2:
            raise PROOF.VerificationFailure('both actual Candidate exchanges remain')


class EvaluatedCandidateContinuationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.manifest = tomllib.loads((ROOT / 'CALLERS.toml').read_text())
        cls.boundaries = {b.identifier: b for b in PROOF._boundary_rows(cls.manifest)}

    def verifies(self, path, source):
        rows = [r for r in self.manifest['protected_file'] if r['path'] == path]
        self.assertEqual(len(rows), 1, path)
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            target = root / path
            target.parent.mkdir(parents=True)
            target.write_text(source)
            PROOF._verify_protected_files(root, {'protected_file': rows})
        require_execute_dominance(path, source)
        require_readonly_and_mounts(path, source)
        require_progress_and_postread_contract(path, source)

    def rejects(self, path, name, marker, replacement='', ordinal=0):
        original = (ROOT / path).read_text()
        self.verifies(path, original)
        code, start, end = span(original, name)
        found = locate(code[start:end], marker, ordinal)
        offset = start + found.start()
        changed = original[:offset] + replacement + original[start + found.end():]
        with self.assertRaises(PROOF.VerificationFailure, msg=(path, name, marker)):
            self.verifies(path, changed)

    def rejects_unused(self, path, name):
        original = (ROOT / path).read_text()
        code, start, end = span(original, name)
        opening = code.index('{', start, end)
        changed = original[:opening + 1] + '\nlet _unused = || async {' + original[opening + 1:end - 1] + '\n}; panic!();\n' + original[end - 1:]
        self.verifies(path, original)
        with self.assertRaises(PROOF.VerificationFailure, msg=(path,name)):
            self.verifies(path, changed)

    def test_all_actual_sources_and_private_functions_are_guarded(self):
        for path in PRODUCT:
            self.verifies(path, (ROOT / path).read_text())
        for path in NEW:
            code = PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code((ROOT / path).read_text()))
            actual = set(re.findall(r'\bfn (\w+)\(', code))
            row = next(r for r in self.manifest['protected_file'] if r['path']==path)
            guarded = {f['function'][3:-1] for f in row['required_function_order']}
            self.assertEqual(actual, guarded, path)
        self.assertTrue(all(v is False for v in self.manifest['authority'].values()))
        ports = PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code((ROOT / AGENT / 'learning_iteration_ports.rs').read_text()))
        self.assertNotIn('read_original_evaluated_attestations', ports)

    def test_exact_concrete_callers_reject_extra_method_or_qualified_calls(self):
        paths = {p for identifier in EXPECTED for p in (self.boundaries[identifier].definition_path, *self.boundaries[identifier].product_callers)}
        paths.add(AGENT + 'cell_q24_no_update_stage_owners.rs')
        sources = {p:PROOF._strip_cfg_test_items(PROOF._strip_rust_non_code((ROOT/p).read_text())) for p in paths}
        for identifier, expected in EXPECTED.items():
            row = self.boundaries[identifier]
            self.assertEqual(row.product_callers, expected, identifier)
            self.assertIn(identifier, self.manifest['privileged_inventory']['required_boundary_ids'])
            PROOF._verify_boundary(ROOT, row, sources, ())
            method = row.symbol.rsplit('::',1)[-1]
            for call in (f'owner.{method}();', f'{row.symbol}(owner);'):
                altered = dict(sources)
                altered[AGENT + 'unregistered_evaluated_candidate.rs'] = f'fn bypass(owner: &{row.receiver_type}) {{ {call} }}'
                with self.assertRaisesRegex(PROOF.VerificationFailure, 'unexpected'):
                    PROOF._verify_boundary(ROOT,row,altered,())
            with self.assertRaises(PROOF.VerificationFailure):
                PROOF._verify_boundary(ROOT,replace(row,product_callers=()),sources,())

    def test_move_only_channels_and_private_cancellation_state(self):
        for field in ('version:', 'selector:', 'next_use:', 'readiness:', 'selector_initial:', 'predecessors:', 'selection:', 'completion:', 'failed:'):
            source = (ROOT/MAIN).read_text()
            start = source.index('pub(super) struct EvaluatedLane {')
            point = source.index('    '+field, start)
            for visibility in ('pub ', 'pub(crate) ', 'pub(super) '):
                changed = source[:point] + '    ' + visibility + source[point+4:]
                with self.assertRaises(PROOF.VerificationFailure): self.verifies(MAIN,changed)
        for field in ('version','selector','next_use','readiness'):
            self.rejects(CHANNELS,'take_original_evaluated_channels',f'self.{field}_initial.take()',f'self.{field}_initial.as_ref()')
        self.rejects_unused(CHANNELS,'take_original_evaluated_channels')

    def test_original_brands_and_same_held_channels_cannot_be_upgraded(self):
        for function in ('ensure_version','ensure_selector','ensure_next_use'):
            self.rejects(BINDING,function,'self.require_predecessors(current)?')
            self.rejects(BINDING,function,'Origin::Recovered','Origin::Fresh')
            self.rejects_unused(BINDING,function)
        for marker in ('snapshot.receipts.len() != 4','snapshot.training_no_update_v2().is_some()',
                       'coordinator.candidate().is_none()','evaluation.training_attestation() != training.attestation()',
                       'self.version.is_some()','self.original_selection.is_some()'):
            self.rejects(CHANNELS,'take_original_evaluated_channels',marker)

    def test_stage_routing_keeps_qualified_candidate_refusal_and_tnu_route(self):
        for marker in ('!is_evaluated_retention(snapshot)','self.evaluated_retention_prefix(snapshot)?',
                       'coordinator.next_stage() != Some(stage)','(Stage::Selection, 4) | (Stage::NextUse, 5)'):
            self.rejects(MAIN,'require_evaluated_retention_stage',marker)
        for function, marker in (
            ('validate_recovery','retention::is_evaluated_retention(snapshot)'),
            ('execute_stage','retention::is_evaluated_retention(snapshot)'),
            ('execute_stage','snapshot.training_no_update_v2().is_none()'),
            ('receipt_attestation','retention::is_evaluated_retention(snapshot)'),
        ): self.rejects(OWNERS,function,marker)
        for path,module in ((OWNERS,'pub(super) mod retention;'),(STATE,'mod evaluated_channels;')):
            original=(ROOT/path).read_text();changed=original.replace(module,'#[cfg(test)]\n'+module,1)
            with self.assertRaises(PROOF.VerificationFailure):self.verifies(path,changed)

    def test_full_prefix_checks_and_actual_predecessor_io_are_mandatory(self):
        for marker in ('self.training_prefix(supplied)?','!(4..=6).contains(&supplied.receipts.len())',
                       'original.record(evaluation.clone(), evaluation.observed_unix_seconds)?',
                       'original.next_stage() != Some(Stage::Selection) || original.candidate().is_none()'):
            self.rejects(MAIN,'evaluated_retention_prefix',marker)
        for marker in ('self.read_original_evaluation_with_originals(four_cut).await?', '.into_parts()',
                       'common.original_dataset.as_ref() != Some(&dataset)',
                       'common.original_training.as_ref() != Some(&training)',
                       'evaluation.snapshot() != four_cut','evaluation.training_attestation() != training.attestation()',
                       'self.verify_original_evaluation(four_cut, &training_cut, &training, &evaluation, fresh)?'):
            self.rejects(MAIN,'evaluated_predecessors',marker)
        # The old mandatory final original read now belongs to the same awaited
        # producer; it was not converted to a cache or metadata comparison.
        for ordinal in (0, 1):
            self.rejects(EVALUATION,'original_evaluation','common.read_prefix(&self.common, &training_cut).await?',ordinal=ordinal)
        self.rejects_unused(MAIN,'evaluated_predecessors')

    def test_unknown_results_and_cancellation_keep_the_lane_fenced(self):
        for path,name,requested in ((S,'original_evaluated_selection','selection_requested'),(C,'original_evaluated_next_use','completion_requested')):
            for marker,replacement in (('lane.failed = true','lane.failed = false'),
                                       ('lane.failed || action == Action::Execute && lane.'+requested,'false'),
                                       ('lane.'+requested+' = true','lane.'+requested+' = false'),
                                       ('if before != after','if before == after'),
                                       ('lane.require_predecessors(&after)?','')):
                self.rejects(path,name,marker,replacement)
            self.rejects_unused(path,name)

    def test_execute_effects_and_root_checks_stay_inside_the_fresh_branch(self):
        for path,name,call in ((S,'original_evaluated_selection','OriginalCircuitEvaluatedSelectionCommandClientV1::execute_selection(selector).await'),
                               (C,'original_evaluated_next_use','OriginalCircuitEvaluatedNextUseCommandClientV1::attest_completed_task(observer).await')):
            self.rejects(path,name,'self.common.origin != Origin::Fresh','self.common.origin == Origin::Fresh')
            self.rejects(path,name,call,'{ let _unpolled = || async { '+call+' }; panic!() }')
            original=(ROOT/path).read_text();code,start,end=span(original,name)
            found=locate(code[start:end],'let dispatched = if action == Action::Execute')
            changed=original[:start+found.start()]+original[start+found.start():start+found.end()].replace('Action::Execute','Action::Readback')+original[start+found.end():]
            with self.assertRaises(PROOF.VerificationFailure):self.verifies(path,changed)

    def test_version_prepare_once_and_original_frame_reserve_are_not_retried(self):
        for marker in ('lane.take_version_request()?','RootResidentLearningEffectGateV3::training_cancellation(gate)',
                       'lane.version_requests >= 128 - VERSION_READBACK_RESERVE - 1',
                       'OriginalCircuitRetainedVersionClientV1::publication_progress(client).await',
                       'self.read_evaluated_version(lane).await?'):
            self.rejects(S,'prepare_evaluated_version',marker)
        self.rejects(S,'read_evaluated_version','OriginalCircuitRetainedVersionClientV1::readback(client).await')
        self.rejects(MAIN,'take_version_request','self.version_requests >= 128','self.version_requests >= 256')
        self.rejects(S,'read_evaluated_version','actual.publication().is_none()','actual.publication().is_some()')
        self.rejects_unused(S,'prepare_evaluated_version')

    def test_pending_is_not_a_current_publication_and_available_requires_full_read(self):
        for marker, replacement in (
            ('Ok(OriginalCircuitEvaluatedVersionProgressV1::Pending) | Err(OriginalCircuitRetainedVersionErrorV1::Busy) => {}',
             'Ok(OriginalCircuitEvaluatedVersionProgressV1::Pending) | Err(OriginalCircuitRetainedVersionErrorV1::Busy) => { return Ok(()); }'),
            ('Ok(OriginalCircuitEvaluatedVersionProgressV1::ReadbackAvailable)',
             'Ok(OriginalCircuitEvaluatedVersionProgressV1::Pending)'),
            ('self.read_evaluated_version(lane).await?;', ''),
            ('self.read_evaluated_version(lane).await?;',
             'let _unused = || async { self.read_evaluated_version(lane).await };'),
            ('Err(_) => return Err(Error::CommitUncertain)', 'Err(_) => return Ok(())'),
        ):
            self.rejects(S, 'prepare_evaluated_version', marker, replacement)

    def test_progress_reserves_a_complete_read_and_later_current_frames(self):
        for replacement in ('lane.version_requests >= 128',
                            'lane.version_requests >= 128 - VERSION_READBACK_RESERVE',
                            'lane.version_requests >= 256 - VERSION_READBACK_RESERVE - 1'):
            self.rejects(S, 'prepare_evaluated_version',
                         'lane.version_requests >= 128 - VERSION_READBACK_RESERVE - 1', replacement)
        original = (ROOT/S).read_text()
        for replacement in ('const VERSION_READBACK_RESERVE: usize = 0;',
                            '// const VERSION_READBACK_RESERVE: usize = 8;\nconst VERSION_READBACK_RESERVE: usize = 0;'):
            changed = original.replace('const VERSION_READBACK_RESERVE: usize = 8;', replacement, 1)
            with self.assertRaises(PROOF.VerificationFailure): self.verifies(S, changed)

    def test_progress_cannot_issue_a_second_prepare_or_hide_a_progress_call(self):
        self.rejects(S, 'prepare_evaluated_version', 'loop {',
                     'loop { OriginalCircuitRetainedVersionClientV1::prepare_original_version(client, cancel).await?;')
        self.rejects(S, 'prepare_evaluated_version',
                     'OriginalCircuitRetainedVersionClientV1::publication_progress(client).await',
                     '{ let _unused = || async { OriginalCircuitRetainedVersionClientV1::publication_progress(client).await }; panic!() }')

    def test_postread_opaque_fields_cannot_be_exposed_cloned_or_constructed_elsewhere(self):
        original = (ROOT/EVALUATION).read_text()
        start = original.index('pub(super) struct PostEvaluationOriginals {')
        for field in ('dataset', 'training', 'evaluation'):
            point = original.index('    ' + field + ':', start)
            for visibility in ('pub ', 'pub(crate) ', 'pub(super) '):
                changed = original[:point] + '    ' + visibility + original[point+4:]
                with self.assertRaises(PROOF.VerificationFailure): self.verifies(EVALUATION, changed)
        changed = original[:start] + '#[derive(Clone)]\n' + original[start:]
        with self.assertRaises(PROOF.VerificationFailure): self.verifies(EVALUATION, changed)
        changed = original + '\nimpl PostEvaluationOriginals { pub(crate) fn forge(dataset: OriginalCellQ24MaterialCommandReceiptV1, training: OriginalCellQ24TrainingCommandReceiptV1, evaluation: OriginalCellEvaluationCommandReceiptV1) -> Self { Self { dataset, training, evaluation } } }\n'
        with self.assertRaises(PROOF.VerificationFailure): self.verifies(EVALUATION, changed)
        caller = (ROOT/MAIN).read_text() + '\nfn forge(dataset: OriginalCellQ24MaterialCommandReceiptV1, training: OriginalCellQ24TrainingCommandReceiptV1, evaluation: OriginalCellEvaluationCommandReceiptV1) { let _forged = PostEvaluationOriginals { dataset, training, evaluation }; }\n'
        with self.assertRaises(PROOF.VerificationFailure): self.verifies(MAIN, caller)

    def test_postread_current_cannot_be_stored_or_returned_without_live_read(self):
        original = (ROOT/EVALUATION).read_text()
        for replacement in ('pub(super) struct EvaluationLane {\n    postread: Option<PostEvaluationOriginals>,',
                            'pub(super) struct EvaluationLane {\n    postread: Option<super::evaluation::PostEvaluationOriginals>,'):
            changed = original.replace('pub(super) struct EvaluationLane {', replacement, 1)
            with self.assertRaises(PROOF.VerificationFailure): self.verifies(EVALUATION, changed)
        self.rejects(EVALUATION, 'read_original_evaluation_with_originals',
                     'self.original_evaluation(snapshot, Action::Readback).await',
                     'Ok(self.evaluation.try_lock()?.postread.take().unwrap())')
        self.rejects(EVALUATION, 'read_original_evaluation_with_originals',
                     'self.original_evaluation(snapshot, Action::Readback).await',
                     'self.original_evaluation(snapshot, Action::Execute).await')
        self.rejects_unused(EVALUATION, 'read_original_evaluation_with_originals')

    def test_postread_values_are_minted_only_after_final_actual_io_and_full_auth(self):
        for marker in ('dataset: common.original_dataset.as_ref().ok_or(Error::CommitUncertain)?.clone()',
                       'training: current_training.clone()', 'evaluation: original.clone()',
                       'auth::verify_prefix(&self.common.material, &training_cut, common, fresh)?',
                       'self.verify_original_evaluation(snapshot, &training_cut, &training, &original, fresh)?'):
            self.rejects(EVALUATION, 'original_evaluation', marker)
        self.rejects(EVALUATION, 'original_evaluation', 'training: current_training.clone()', 'training: training.clone()')
        original = (ROOT/EVALUATION).read_text()
        code, start, end = span(original, 'original_evaluation')
        post = locate(code[start:end], 'let post = PostEvaluationOriginals {')
        post_start = start + post.start()
        post_end = PROOF._rust_item_end(code, post_start)
        self.assertIsNotNone(post_end)
        post_end = code.index(';', post_end) + 1
        block = original[post_start:post_end]
        final_read = locate(code[start:end], 'common.read_prefix(&self.common, &training_cut).await?;', 1)
        read_start = start + final_read.start()
        changed = (original[:read_start] + block + '\n' + original[read_start:post_start]
                   + original[post_end:])
        with self.assertRaises(PROOF.VerificationFailure): self.verifies(EVALUATION, changed)
        changed = original.replace('lane.failed = false;\n        Ok(post)', 'Ok(post)', 1)
        changed = changed[:post_start] + 'lane.failed = false;\n        ' + changed[post_start:]
        with self.assertRaises(PROOF.VerificationFailure): self.verifies(EVALUATION, changed)
        self.rejects_unused(EVALUATION, 'original_evaluation')
        self.rejects_unused(EVALUATION, 'into_parts')
        self.rejects(MAIN, 'evaluated_predecessors',
                     'common.original_training.as_ref() != Some(&training)',
                     'common.original_training.as_ref().map(|old| old.receipt()) != Some(training.receipt())')

    def test_c_reads_actual_s_and_separate_readiness_before_dispatch(self):
        for marker in ('OriginalCircuitEvaluatedSelectionCommandClientV1::readback(selector)',
                       'self.read_evaluated_version(lane).await?', 'lane.ensure_readiness(self, &before, &selection)?',
                       'observation != &current.receipt().observation', 'OriginalCircuitEvaluatedNextUseCommandClientV1::readback(observer)'):
            self.rejects(C,'original_evaluated_next_use',marker)
        for marker in ('for _ in 0..128','OriginalCircuitEvaluatedCompletionReadinessClientV1::read_current(readiness)',
                       'self.evaluated_predecessors(before.evaluation.snapshot()).await?',
                       '!auth::same_selection(selection, &current_selection)','self.verify_evaluated_selection('):
            self.rejects(C,'await_evaluated_c',marker)
        self.rejects_unused(C,'await_evaluated_c')

    def test_cold_readback_cannot_execute_or_request_a_future_root_cut(self):
        for path,name in ((MAIN,'read_original_evaluated_retention'),(MAIN,'evaluated_retention_attestation'),
                          (BATCH,'read_original_evaluated_attestations'),(S,'read_evaluated_version')):
            original=(ROOT/path).read_text();code,start,end=span(original,name);opening=code.index('{',start,end)
            for injected in ('RootResidentLearningEffectGateV3::require_current(gate, snapshot, scope).await?;',
                             'OriginalCircuitEvaluatedSelectionCommandClientV1::execute_selection(selector).await?;'):
                changed=original[:opening+1]+injected+original[opening+1:]
                with self.assertRaises(PROOF.VerificationFailure):self.verifies(path,changed)

    def test_batch_requires_this_calls_actual_reads_and_full_signature_tail(self):
        for marker in ('self.read_original_evaluation(snapshot).await?',
                       'self.original_evaluated_selection(snapshot, Action::Readback)',
                       'self.original_evaluated_next_use(snapshot, Action::Readback)',
                       'selection.snapshot() != snapshot','completion.snapshot() != snapshot'):
            self.rejects(BATCH,'read_original_evaluated_attestations',marker)
        for marker in ('common.original_dataset.as_ref() != Some(&current.dataset)',
                       'common.original_training.as_ref() != Some(&current.training)',
                       'current.dataset.attestations().len() != 2',
                       'common_auth::verify_prefix(&self.common.material, &training_cut, common, fresh)?',
                       'self.verify_original_evaluation(snapshot, &training_cut, &current.training, &current.evaluation, fresh)?',
                       'common.records.get(index).map(|record| &record.1) != Some(signature)'):
            self.rejects(BATCH,'evaluated_predecessor_signatures',marker)
        self.rejects_unused(BATCH,'read_original_evaluated_attestations')
        self.rejects_unused(BATCH,'evaluated_predecessor_signatures')

    def test_root_still_revalidates_its_current_authority_and_every_signature(self):
        for marker in ('ResidentOriginalStageOwnersV3::read_original_evaluated_attestations(stages, snapshot).await?',
                       'if has_model', 'stages.validate_recovery(snapshot).await?',
                       'let (_, fresh) = owner.read(cancellation).await?',
                       'ResidentOriginalStageOwnersV3::require_initial(', 'verify_original_evidence('):
            self.rejects(ROOT_AUTH,'original_attestations',marker)
        self.rejects_unused(ROOT_AUTH,'original_attestations')
        self.rejects(STAGES,'read_original_evaluated_attestations','Self::NoUpdate(_) => Err(Error::WrongScope)','Self::NoUpdate(_) => Ok(None)')

    def test_complete_scopes_fresh_clock_and_signed_role_separation_are_required(self):
        for name,markers in (
            ('verify_evaluated_selection',('original.original_context().receipt_context_binding() != expected.receipt_context_binding()',
                'original.snapshot().receipts.len() != 5','coordinator.next_stage() != Some(Stage::NextUse)',
                'verify_signed_actor_separation(&predecessor, &verified, fresh)')),
            ('verify_evaluated_next_use',('!same_selection(selection, original.original_selection())',
                'original.snapshot().receipts.len() != 6','coordinator.next_stage().is_some()',
                'verify_signed_actor_separation(&predecessor, &verified, fresh)')),
            ('verify_evaluated_retention_signature',('receipt.observed_unix_seconds > signature.issued_at',
                'signature.issued_at > fresh','verified.principal().principal_id != receipt.actor_id',
                'verified.trust_digest() != self.common.material.initial.owners.evidence_trust_digest',
                'verified.objective_digest() != self.common.material.initial.request.envelope.objective_digest')),
        ):
            for marker in markers:self.rejects(AUTH,name,marker)
            self.rejects_unused(AUTH,name)


if __name__ == '__main__':
    unittest.main()
