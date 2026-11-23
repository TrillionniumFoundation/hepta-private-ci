"""Exercise two isolated native source identities using the same test-only observer."""
import hashlib
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(os.environ['TEST_EVIDENCE'])
SOURCE = Path(os.environ['RUNNER_TEMP'])
ORIGINAL = [
    'original_artifact_head_signs_once_and_cold_reads_saved_signature',
    'original_artifact_head_lost_reply_reads_original_without_recreating_writer',
    'original_artifact_head_restored_source_cannot_revive_consumed_connection',
]
EMIT = 'original_codec_emits_five_canonical_responses'
READ = 'original_codec_reads_other_products_five_responses'
SWEEP = 'original_codec_checks_status_partition_and_bounds'


def run(binary, label, short, corpus):
    dest = ROOT / (label + '.log')
    listing = subprocess.check_output([binary, '--list'], text=True).splitlines()
    names = []
    for name in short:
        matches = [s.removesuffix(': test') for s in listing if s.endswith('::' + name + ': test')]
        if len(matches) != 1:
            raise ValueError((name, matches))
        names.append(matches[0])
    env = dict(os.environ, CANONICAL_HEAD_CORPUS=str(corpus))
    with dest.open('wb') as handle:
        result = subprocess.run([binary, '--exact', '--test-threads=1', *names], env=env,
                                stdout=handle, stderr=subprocess.STDOUT)
    contents = dest.read_text()
    matched = re.findall(r'^test (\S+) \.\.\. (ok|FAILED|ignored)$', contents, re.M)
    print(label, result.returncode, matched, flush=True)
    if result.returncode or sorted(matched) != sorted((n, 'ok') for n in names):
        print(contents[-5000:])
        raise ValueError(label)
    return dict(cases=matched, log_sha256=hashlib.sha256(dest.read_bytes()).hexdigest())


def digest(path):
    h = hashlib.sha256()
    with path.open('rb') as file:
        for chunk in iter(lambda: file.read(1 << 20), b''):
            h.update(chunk)
    return h.hexdigest()


def main():
    arms = ('base', 'candidate')
    result = {}
    for arm in arms:
        binary = SOURCE / ('canonical-head-' + arm)
        corpus = ROOT / (arm + '-frames')
        corpus.mkdir()
        result[arm] = dict(elf=digest(binary), source=(ROOT / (arm + '-source.txt')).read_text().strip())
        result[arm]['original'] = run(binary, arm + '-original', ORIGINAL, corpus)
        result[arm]['wire'] = run(binary, arm + '-wire', [EMIT, SWEEP], corpus)
        result[arm]['frames'] = {p.name: digest(p) for p in sorted(corpus.iterdir())}
        assert len(result[arm]['frames']) == 5
    assert result['base']['elf'] != result['candidate']['elf']
    assert result['base']['frames'] == result['candidate']['frames']
    for arm, peer in [('base','candidate'), ('candidate','base')]:
        result[arm]['cross_read_from_' + peer] = run(
            SOURCE / ('canonical-head-' + arm), arm + '-cross', [READ], ROOT / (peer + '-frames'))
    (ROOT / 'results.json').write_text(json.dumps(result, indent=2, sort_keys=True)+'\n')
    print(json.dumps(result, sort_keys=True))


if __name__ == '__main__':
    main()
