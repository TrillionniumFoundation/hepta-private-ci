"""Independent metadata/AST review of shared pair construction; no model import."""

import ast
import hashlib
import json
from pathlib import Path
import time


HERE = Path(__file__).resolve().parent
ADVANCE = HERE.parents[1]


def sha(path):
    with Path(path).open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest()


def main():
    helpers = {'cases.py': '39fece37565e754ef357085e77f1314739f87eb81aa3cffc8aa5bd5d0bbca04c',
               'input_codec.py': 'ebee9bd16b983b8374066fceb87785d7673915afc74a1260454a0b4104b5c6dd'}
    for name, expected in helpers.items():
        if sha(ADVANCE / name) != expected:
            raise ValueError('Reviewed helper identity changed: ' + name)
    allocation = json.loads((ADVANCE / 'SOURCE_ALLOCATION.json').read_text())
    checks = {}
    for name in ('confirmation', 'qualification_id'):
        selected = allocation['roles'][name]
        records, audio = selected['source_records'], selected['audio_rows_by_source_digit']
        if len(records) != 2 * selected['pair_count'] or len(audio) != len(records):
            raise ValueError('Source and audio task census differs')
        count = 0
        for pair in range(selected['pair_count']):
            writer = selected['pair_writer_ids'][pair]
            speaker = selected['speaker_by_writer'][str(writer)]
            for swap in (False, True):
                indices = [2 * pair, 2 * pair + 1]
                if swap:
                    indices.reverse()
                expected = [records[index]['label'] for index in indices]
                if ([audio[index]['label'] for index in indices] != expected
                        or any(records[index]['writer'] != writer or audio[index]['speaker'] != speaker for index in indices)):
                    raise ValueError('A public swap misaligns source pixels, digit request or recorded speech')
                count += 1
        checks[name] = {'pairs': selected['pair_count'], 'both_swap_permutations_checked': count,
                        'writer_speaker_alignment': True}
    tree = ast.parse((ADVANCE / 'cases.py').read_text())
    prepare = next(node for node in tree.body if isinstance(node, ast.FunctionDef) and node.name == 'prepare_task')
    if any(isinstance(node, ast.Attribute) and node.attr == 'target' for node in ast.walk(prepare)):
        raise ValueError('Private scoring target unexpectedly enters public task preparation')
    loader_calls = [node for node in ast.walk(prepare) if isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name) and node.func.id == 'load_audio']
    if len(loader_calls) != 1:
        raise ValueError('Unexpected initial-waveform access surface')
    caller = ADVANCE / 'joint/confirmation_data.py'
    source = caller.read_text(); ast.parse(source)
    if ('if not self.old:' not in source or 'source = construct_case(' not in source
            or 'prepared = {route: prepare_task(' not in source):
        raise ValueError('Formal joint caller does not route through reviewed input preparation')
    result = {'schema': 'hepta.advance.shared-input-independent-review.v1',
        'status': 'static_and_metadata_passed', 'recorded_ns': time.time_ns(),
        'helper_sha256': helpers, 'formal_joint_caller_sha256': sha(caller),
        'source_allocation_sha256': sha(ADVANCE / 'SOURCE_ALLOCATION.json'),
        'metadata_permutation_checks': checks,
        'reviewed_dataflow': [
            'Original source order is 2*i,2*i+1. Public make_batch token9/10 determines keep/swap; a single reversal reorders source pixels, literal digit requests and WAVs together.',
            'construct_case checks source IDs and target equality only in trusted construction. prepare_task never reads target. Literal text supplies its explicitly requested digits; image host receives only Observation.',
            'Image/video preparation does not call load_audio. Initial audio opens actual WAVs and exposes no late copy. Text also exposes no late audio. Image/video late metadata is limited to path/SHA and stays in the trusted driver.',
            'Video uses source pixels in public command order, constructed20-frame motion, real lossless libx264rgb MP4, actual independent FFmpeg decode and byte equality. It verifies every PTS,5fps and4s duration before model input.',
            'The formal joint branch now invokes construct_case plus prepare_task. The direct unencoded motion tensor path is confined to its already frozen old_smoke branch.'
        ],
        'remaining_scope_requirements': [
            'This review executes metadata/AST checks, not Torch, FFmpeg or a model. Actual helper runtime receipts are still required from executed probes/final requests.',
            'PreparedTask receipt/late paths contain source metadata and filenames that may reveal class. Only PublicTask tensors may enter a model; metadata must remain driver/custody data. This is an auditable function boundary, not a malicious-process sandbox.',
            'Formal protocols must bind these exact helpers, their transitive dependencies and actual FFmpeg/FFprobe executables. A helper pin alone is insufficient unless the actual caller executes it.',
            'Digit-motion input is constructed source video; no claim of natural-video or arbitrary text competence follows. The factorized audio likelihood remains a separately declared model assumption.'
        ],
        'review_source_sha256': sha(__file__), 'models_or_source_role_loaders_called': False,
        'new_audio_decoded_or_scored': False, 'new_image_model_outcomes_opened': False}
    output = HERE / 'INPUT_REVIEW.json'
    with output.open('x') as stream:
        json.dump(result, stream, indent=2, sort_keys=True); stream.write('\n')
    print(json.dumps({'status': result['status'], 'review_sha256': sha(output),
                      'metadata_permutations': sum(row['both_swap_permutations_checked'] for row in checks.values())}))


if __name__ == '__main__':
    main()
