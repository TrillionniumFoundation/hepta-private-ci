"""Read raw native/SQLite evidence instead of trusting study PASS fields.

SQLite semantic replay deliberately reuses the existing reducer. Native signature
validation is performed by the native owners/tests; this auditor adds independent
raw callback, request, effect, terminality and restart comparisons, not attestation.
"""
import argparse
import hashlib
import json
from pathlib import Path
import sqlite3
from contextlib import closing
import tempfile
import unittest

from four_gate_common import require
from fbsde_checkpoint_audit import validate_rows
from fbsde_native_rule_study import PUBLIC, CONTEXT
from fbsde_transfer import TransferProblem, OPS

COUNTS = dict(successful=6, concurrent_finish=1, finaluse_revoked_after_claim=0,
    finaluse_revoked_restart=0, rule_revoked=0, signed_current_corrupt=0, selection_expired=0,
    late_inference=1, driver_unknown=1, driver_panic=1, local_finish_unknown=1,
    native_restart=1, rule_restart=0, recovery_new_selection=2, unverified_source=0)


def audit(root, summary=None):
    summary = summary if summary is not None else json.loads((root / 'summary.json').read_text())
    require(summary['production_qualified'] is False and summary['four_gate_changed'] is False,
            'research qualification boundary')
    cases = summary['cases']
    require(len(cases) == len(COUNTS) and {case['name'] for case in cases} == set(COUNTS), 'case inventory')
    table = TransferProblem.build(PUBLIC, CONTEXT).table[1]
    expected = [[state[coordinate] for coordinate in OPS[table[index]]] for index, state in enumerate(OPS)]
    for case in cases:
        name = case['name']; directory = root / name
        # The independently stored per-case record must agree with its summary.
        require(json.loads((directory / 'case.json').read_text()) == case, 'per-case summary mismatch')
        require(case['production_qualified'] is False, 'case promotion claim')
        returned = case['returned']
        if name == 'successful': require(returned == expected and not case['refusals'], 'six actual native outputs')
        elif name == 'concurrent_finish': require(returned == expected[:1] and len(case['refusals']) == 1, 'concurrent delivery')
        elif name == 'recovery_new_selection':
            require(returned == expected[:1]*2 and len(case['refusals']) == 1, 'fresh native recovery outputs')
            require(case['recovery']['status']['context']['generation'] == 2 and
                len(case['recovery']['calls']) == case['recovery']['status']['recovery_attempts'] and
                0 < len(case['recovery']['calls']) <= 5, 'paid recovery budget preservation')
        else: require(not returned and case['refusals'], 'refused work returned output')
        entries_path = directory / 'native/inference-driver.jsonl'
        entries = [json.loads(row) for row in entries_path.read_text().splitlines()] if entries_path.exists() else []
        require(len(entries) == COUNTS[name], 'actual callback entry inventory')
        transcript = case['native_transcript']
        admissions = [row['request'] for row in transcript if row['request']['command'] in ('init','install_revision')]
        init = admissions[0]
        for admission in admissions:
            payload = bytes.fromhex(admission['payload_hex'])
            require(hashlib.sha256(payload).hexdigest() == admission['checkpoint_digest'], 'selected exact payload digest')
            bundle = json.loads(payload)
            require(bundle['table']['effects'] == list(table) and bundle['revision'] == admission['rule_revision'] and
                bundle['generation'] == admission['generation'], 'immutable known rule fixture')
        if name == 'recovery_new_selection':
            require(len(admissions) == 2 and admissions[1]['generation'] == 2 and admissions[1]['rule_revision'] > 0,
                    'fresh native candidate and independent selection absent')
        operations = [row for row in transcript if row['request']['command'] == 'execute']
        for entry in entries:
            matching = [row for row in operations if f"research.request.{row['request']['sequence']}" == entry['request_id']]
            # A crashing response is absent from the transport transcript; the
            # SQLite request and assigned native journal preserve its identity.
            require(matching or name == 'driver_panic', 'foreign native driver entry')
            require(entry['selected_payload_digest'] in {admission['checkpoint_digest'] for admission in admissions}, 'driver selected different bytes')
        journal_path = directory / 'native/inference.journal'
        journal = journal_path.read_text().splitlines()
        submits = [row.split('|') for row in journal if row.startswith('submit|')]
        assignments = [row.split('|') for row in journal if row.startswith('assign|')]
        settlements = [row.split('|') for row in journal if row.startswith('settle|')]
        require(len({row[1] for row in submits}) == len(submits), 'duplicate durable native request')
        require(all(row[1] in {item[1] for item in assignments} for row in settlements), 'settlement without intent')
        if name in ('successful','concurrent_finish','late_inference','local_finish_unknown','native_restart','recovery_new_selection'):
            require(len(settlements) == COUNTS[name] and all(row[9:11] == ['1','completed'] for row in settlements),
                    'actual completed observations retained')
        if name == 'driver_unknown': require(len(settlements) == 1 and settlements[0][9:11] == ['0','none'], 'unknown work released')
        if name == 'driver_panic':
            require(case['native_exit_code'] == 101 and len(assignments) == 1 and not settlements, 'panic must retain assigned work')
            require('injected research callback panic after actual table execution' in (directory / 'native/native-stderr.log').read_text(), 'panic stderr missing')
        if name == 'native_restart': require(len(entries) == 1 and any(row['response'].get('error') == 'AlreadyClaimed' for row in operations), 'restart nonce replay')
        if name == 'local_finish_unknown':
            require(case['wrapper_costs'][0]['native_response']['ok'] and not case['wrapper_costs'][0]['returned'],
                    'uncertain local finish delivered native success')
        db = directory / 'rule/rule.sqlite3'
        with closing(sqlite3.connect(db)) as connection:
            rows = [dict(event=json.loads(event), snapshot=json.loads(snapshot), digest=identity)
                for _, _, event, snapshot, identity in connection.execute('SELECT * FROM checkpoint ORDER BY seq')]
        validate_rows(rows)
        if 'last_acknowledged_anchor' in case:
            anchor = case['last_acknowledged_anchor']
            require(rows[anchor['sequence']]['digest'] == anchor['digest'], 'independent last acknowledgement absent')
        if name == 'local_finish_unknown': require(rows[-1]['event']['event'] == 'finish', 'lost reply did not actually commit finish')
        require(case['parent_cpu_ns'] > 0 and case['wall_ns'] > 0 and case['file_bytes'] > 0, 'actual cost observation')
        for row in operations:
            if row['response']['ok']:
                response, request = row['response'], row['request']
                require(response['effect'] == [x // (1 << 24) for x in request['expected_prediction_q24']] and
                    response['checkpoint_digest'] == request['checkpoint_digest'] and response['journal_bytes'] > 0,
                    'actual native response binding/cost')
    require(summary['native_children_user_cpu_s'] > 0 and summary['native_children_system_cpu_s'] >= 0, 'native child CPU inventory')
    return len(cases)


class MutationTests(unittest.TestCase):
    root = None
    def test_original_raw_evidence(self): self.assertEqual(audit(self.root), len(COUNTS))

    def mutate(self, edit):
        with tempfile.TemporaryDirectory() as temporary:
            # Symlinks reference unmodified original raw files; only the case
            # records being mutated get independent local bytes.
            root = Path(temporary)
            for name in COUNTS: (root/name).mkdir()
            summary = json.loads((self.root/'summary.json').read_text())
            edit(summary)
            for case in summary['cases']:
                directory = root/case['name']
                (directory/'native').symlink_to((self.root/case['name']/'native').resolve(), target_is_directory=True)
                (directory/'rule').symlink_to((self.root/case['name']/'rule').resolve(), target_is_directory=True)
                (directory/'case.json').write_text(json.dumps(case))
            with self.assertRaises(ValueError): audit(root, summary)

    def test_native_pass_flags_cannot_grant_production(self): self.mutate(lambda s: s.update(production_qualified=True))
    def test_callback_inventory_cannot_be_removed(self): self.mutate(lambda s: s['cases'].pop())
    def test_late_completed_observation_cannot_become_delivery(self):
        self.mutate(lambda s: next(c for c in s['cases'] if c['name']=='late_inference')['returned'].append([0,2,1]))
    def test_wrong_native_output_is_rejected(self):
        self.mutate(lambda s: s['cases'][0]['native_transcript'][1]['response'].update(effect=[0,1,2]))
    def test_old_checkpoint_anchor_cannot_be_relabelled(self):
        self.mutate(lambda s: s['cases'][0]['last_acknowledged_anchor'].update(digest='0'*64))
    def test_panic_work_cannot_be_declared_terminal(self):
        self.mutate(lambda s: next(c for c in s['cases'] if c['name']=='driver_panic').update(native_exit_code=0))


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('directory', type=Path)
    args = parser.parse_args()
    MutationTests.root = args.directory.resolve()
    unittest.main(argv=['native-rule-artifact-checks','-v'])
