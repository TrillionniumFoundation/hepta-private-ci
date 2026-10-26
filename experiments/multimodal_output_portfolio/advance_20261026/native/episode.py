"""One actual model/owner/media lifecycle with causally late external speech."""

import time
from pathlib import Path

from .client import Native, descriptor
from .common import write


def run_episode(host, public_task, *, binary, template, directory, case_id, source_group,
                policy, source_audio_root=None, source_audio_rows=None,
                mode='development', numeric=True, missing=False, recover=False):
    """No ground-truth argument. Source identity fields do not enter the model.

    source_audio_rows are inert path/SHA metadata until an acquire action is
    committed. A fresh owner is allocated for every independent source/policy.
    """
    directory = Path(directory)
    spec = descriptor(template, directory, f'{case_id}.{policy}', source_group, policy, mode, numeric)
    began = time.perf_counter_ns()
    native = Native(binary, spec, directory / 'owner')
    try:
        if missing:
            features, encoding = [0] * 176, {'actual_encoder_calls': 0, 'explicit_missing': True, 'encoder_wall_ns': 0}
            route = 'image'
        else:
            features, encoding = host.encode(public_task)
            route = public_task.route
        write(directory / 'PUBLIC_ENCODING.json', {'features': features, 'encoding': encoding,
            'hidden_target_supplied': False, 'initial_waveform_opened': route == 'audio' and not missing,
            'late_waveform_opened': False, 'future_waveform_opened_before_acquire': False, 'fresh_owner': native.ready})
        horizon = 2 if source_audio_rows is not None else 1
        first = native.decide(case_id + '.h2', case_id, features, route, horizon, missing)
        write(directory / 'DECISION_H2.json', first)
        receipts, decision = [], first
        if recover and first['decision']['selected_action'] is not None:
            before = native.close(pending=True)
            native = Native(binary, spec, directory / 'owner', resume=True)
            write(directory / 'RECOVERY.json', {'before': before, 'after': native.ready['status'],
                'disconnect_was_graceful_pending_process_exit': True})
        if decision['decision']['selected_action'] == 101:
            receipt_path = directory / 'EXTERNAL_AUDIO.json'
            receipt = host.acquire(decision, source_audio_root, source_audio_rows, source_group, receipt_path)
            observed = native.observe(decision, receipt_path)
            receipts.append({'kind': 'external_audio', 'receipt': receipt, 'owner_commit': observed})
            write(directory / 'COMMITTED_EXTERNAL_AUDIO.json', observed)
            decision = native.decide(case_id + '.h1', case_id, features, route, 1, False, observed['outcome_digest'])
            write(directory / 'DECISION_H1.json', decision)
        observed_output = None
        if decision['decision']['selected_action'] is not None:
            receipt_path = directory / 'ACTUAL_OUTPUT.json'
            receipt, observed_output = host.emit(decision, directory / 'media', receipt_path)
            observed = native.observe(decision, receipt_path)
            receipts.append({'kind': 'output', 'receipt': receipt, 'owner_commit': observed})
            write(directory / 'COMMITTED_OUTPUT.json', observed)
        closed = native.close()
        result = {'schema': 'hepta.advance.actual-owner-episode.v1', 'case_id': case_id,
            'source_group': source_group, 'policy': policy, 'mode': mode, 'route': route,
            'initial_action': first['decision']['selected_action'], 'final_action': decision['decision']['selected_action'],
            'actual_external_acquisitions': int(any(r['kind'] == 'external_audio' for r in receipts)),
            'actual_output_bundle': observed_output is not None, 'public_output_observation': observed_output,
            'closed_owner': closed, 'receipts': receipts, 'encoder': encoding,
            'whole_episode_wall_ns': time.perf_counter_ns() - began, 'private_target_read_by_online': False}
        write(directory / 'EPISODE.json', result)
        return result
    finally:
        native.finish_if_alive()
