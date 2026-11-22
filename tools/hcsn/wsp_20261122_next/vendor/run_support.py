"""Phase admission and bounded process accounting; no scientific work on import."""
from datetime import datetime, timezone
from pathlib import Path
import os
import resource
import signal
import time
from data_contract import read, verify, digest, canonical


def utc():
    return datetime.now(timezone.utc).isoformat()


def authenticate_protocol(path):
    protocol = read(path)
    if protocol['schema'] != 'hepta-value-retention-frozen-v1':
        raise ValueError('a draft does not authorize science')
    for group in ('source_pins', 'semantic_sources', 'provenance_sources'):
        for item in protocol[group].values():
            verify(item)
    verify(protocol['draft_pin'])
    for item in protocol['review_pins']:
        verify(item)
    verify(protocol['preflight_pin'])
    return protocol, digest(Path(path).read_bytes())


def verify_originals(protocol):
    for fit in protocol['input_specs'].values():
        for item in fit.values():
            verify(item)
    for group in ('source_pins', 'semantic_sources', 'provenance_sources'):
        for item in protocol[group].values():
            verify(item)
    for item in protocol['history_inputs'] + [protocol['public_domain_source'], protocol['draft_pin']]:
        verify(item)
    return True


def bounded(protocol, phase):
    limits = protocol['resources'][phase]
    affinity = protocol['resources']['affinity_CPU']
    os.sched_setaffinity(0, {affinity})
    resource.setrlimit(resource.RLIMIT_AS, (protocol['resources']['address_space_bytes'],) * 2)
    resource.setrlimit(resource.RLIMIT_CPU, (limits['CPU_soft'], limits['CPU_hard']))
    def expired(*unused):
        raise TimeoutError('frozen phase CPU/wall limit')
    signal.signal(signal.SIGXCPU, expired)
    signal.signal(signal.SIGALRM, expired)
    signal.alarm(limits['wall_hard'])
    def check():
        if time.process_time() >= limits['CPU_soft']:
            expired()
    return check


def resource_record(wall_start):
    return dict(CPU_seconds=time.process_time(), wall_seconds_from_entry=time.perf_counter() - wall_start,
                peak_RSS_bytes=resource.getrusage(resource.RUSAGE_SELF).ru_maxrss * 1024,
                affinity=sorted(os.sched_getaffinity(0)),
                thread_environment={key: os.environ.get(key) for key in
                                    ('OPENBLAS_NUM_THREADS', 'OMP_NUM_THREADS', 'MKL_NUM_THREADS')},
                scope='Process CPU includes import work; supervisor measures complete subprocess lifetime and its own overhead separately')


def semantic_manifest_sha(protocol):
    return digest(canonical(protocol['semantic_sources']).encode())
