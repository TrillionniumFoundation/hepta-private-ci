"""Read retained ordinary Start observations; never issue authority or native counts."""
import hashlib
import json
from pathlib import Path
import uuid

SCHEMA = 'hepta.ordinary-source-start-observation.v1'
OWNER = '00000000-0000-4000-8000-000000000119'
READ_TIMEOUT = 'invalid supervisor value: supervisord read timed out'
JSON_LIMIT = 2 * 1024 * 1024
FILES = ('source-start-request.json', 'source-start-response.json',
         'source-start-observation.json', 'source-service-status.json',
         'supervisor-process.json', 'native-agentd-build.json', 'summary.json')


class StartObservationError(ValueError):
    def __init__(self, message, hashes):
        super().__init__(message)
        self.hashes = hashes


def need(condition, message):
    if not condition:
        raise ValueError(message)


def integer(value, name, minimum=0):
    need(type(value) is int and minimum <= value < 2**64, name)
    return value


def digest(value):
    need(type(value) is str and len(value) == 64
         and all(c in '0123456789abcdef' for c in value), 'canonical digest')


def same(left, right):
    # Python equality treats True == 1; evidence phase identity must not.
    return json.dumps(left, sort_keys=True) == json.dumps(right, sort_keys=True)


def unique(pairs):
    result = {}
    for key, value in pairs:
        need(key not in result, 'duplicate JSON field')
        result[key] = value
    return result


def status_identity(status, epoch):
    need(type(status) is dict and status['agent_id'] == OWNER, 'source Agent identity')
    integer(status['control_revision'], 'source control revision')
    integer(status['lifecycle_generation'], 'source lifecycle generation')
    for name in ('active', 'healthy', 'release_change_pending'):
        need(type(status[name]) is bool, 'boolean status field: ' + name)
    for name in ('process_id', 'spawn_generation', 'runtime_generation'):
        if status[name] is not None:
            integer(status[name], 'source runtime identity: ' + name, 1)
    fence = status['control_fence']
    need(type(fence) is dict and fence['supervisor_epoch'] == epoch, 'source Supervisor epoch')
    for name in ('agent_id', 'lifecycle', 'lifecycle_generation', 'spawn_generation',
                 'runtime_generation', 'current_release', 'previous_release', 'release_change_pending'):
        need(type(fence[name]) is type(status[name]) and fence[name] == status[name],
             'source fence/status mismatch: ' + name)
    digest(fence['state_digest'])


def source_runtime(status, before, epoch, release, revision):
    status_identity(status, epoch)
    need(status['control_revision'] == revision and status['active'] is True
         and status['process_id'] is not None and status['spawn_generation'] == 5
         and status['current_release'] == release
         and status['previous_release'] == before['previous_release']
         and status['release_change_pending'] is False, 'one Start runtime/revision binding')
    generation = {'starting': 5, 'running': 6}.get(status['lifecycle'])
    need(generation is not None and status['lifecycle_generation'] == generation
         and status['runtime_generation'] == generation, 'Starting5 to Running6 lifecycle')
    need(status['lifecycle'] != 'starting' or status['healthy'] is False,
         'Starting cannot be healthy')


def verify_documents(documents):
    request, response, final, service, process, build, summary = (documents[p] for p in FILES)
    request_keys = {'schema', 'started_at_unix_micros', 'supervisor_epoch', 'release',
                    'spawn_generation', 'start_calls', 'readbacks', 'before', 'request'}
    need(set(request) == request_keys and request['schema'] == SCHEMA,
         'exact source Start request schema')
    need(request['start_calls'] == integer(request['start_calls'], 'one Start call', 1) == 1
         and integer(request['spawn_generation'], 'source spawn generation', 1) == 5,
         'one Start call and original spawn5 required')
    integer(request['started_at_unix_micros'], 'source Start timestamp', 1)
    epoch = request['supervisor_epoch']
    need(type(epoch) is str and str(uuid.UUID(epoch)) == epoch
         and uuid.UUID(epoch).int != 0, 'canonical non-zero Supervisor epoch')
    release = request['release']
    need(type(release) is str and 0 < len(release) <= 128
         and release == build['source_release'], 'source release differs from actual build record')
    need(summary['schema'] == 'hepta.ordinary-native-upgrade-study.v1'
         and integer(summary['source_spawn_generation'], 'summary source spawn', 1) == 5,
         'ordinary-upgrade summary source identity')
    health = process['health']
    need(health['ready'] is True and health['supervisor_epoch'] == epoch
         and integer(health['process_id'], 'Supervisor health PID', 1)
         == integer(process['process_id'], 'spawned Supervisor PID', 1),
         'Supervisor health/process identity')
    digest(process['binary_sha256'])
    digest(build['binary_sha256'])
    need(process['production_authority_build_required'] is True,
         'original production-authority fixture missing')
    before = request['before']
    status_identity(before, epoch)
    need(before['lifecycle'] == 'stopped' and before['lifecycle_generation'] == 4
         and before['active'] is False and before['healthy'] is False
         and all(before[k] is None for k in ('process_id', 'spawn_generation',
                                             'runtime_generation', 'current_release', 'previous_release'))
         and before['release_change_pending'] is False, 'original inactive Stopped4 fixture')
    revision = before['control_revision'] + 1
    integer(revision, 'source Start revision overflow', 1)
    need(same(request['request'], {'fence': before['control_fence'], 'release_id': release})
         and request['readbacks'] == [], 'exact original Start request')
    need(set(response) == request_keys | {'start_result'}
         and all(same(response[k], request[k]) for k in request), 'request/response phase substitution')
    need(set(final) == set(response) | {'result', 'monotonic_elapsed_micros'}
         and all(same(final[k], response[k]) for k in response if k != 'readbacks'),
         'response/final phase substitution')
    result = response['start_result']
    seen_revision, process_id = False, None
    if result.get('state') == 'accepted':
        need(set(result) == {'state', 'response'}, 'exact accepted Start response')
        receipt = result['response']
        need(set(receipt) == {'operation', 'accepted_state_digest', 'agent', 'production_receipt'}
             and receipt['operation'] == 'start'
             and receipt['accepted_state_digest'] == before['control_fence']['state_digest']
             and receipt['production_receipt'] is None, 'original Start accepted receipt')
        source_runtime(receipt['agent'], before, epoch, release, revision)
        seen_revision, process_id = True, receipt['agent']['process_id']
    else:
        need(result == {'state': 'unknown', 'error': READ_TIMEOUT},
             'only original exact read timeout permits Unknown readback')
    elapsed = integer(final['monotonic_elapsed_micros'], 'Start observation elapsed')
    readbacks = final['readbacks']
    need(type(readbacks) is list and 0 < len(readbacks) <= 1024, 'bounded nonempty Start readbacks')
    previous_time, last_status = 0, None
    running_seen = False
    for index, observed in enumerate(readbacks):
        tick = integer(observed['monotonic_elapsed_micros'], 'Start readback time')
        need(previous_time <= tick <= elapsed and tick < 60_000_000,
             'readback chronology/original 60s readiness bound')
        previous_time = tick
        if 'error' in observed:
            need(set(observed) == {'monotonic_elapsed_micros', 'error'}
                 and observed['error'] == READ_TIMEOUT, 'non-timeout readback error')
            continue
        need(set(observed) == {'monotonic_elapsed_micros', 'status'}, 'exact readback shape')
        status = observed['status']
        status_identity(status, epoch)
        if status['control_revision'] == before['control_revision']:
            need(not seen_revision and same(status, before), 'state changed before Start revision or regressed')
            continue
        source_runtime(status, before, epoch, release, revision)
        seen_revision = True
        need(process_id is None or status['process_id'] == process_id, 'source process changed after Start')
        process_id = status['process_id']
        need(not running_seen or status['lifecycle'] == 'running', 'source lifecycle regressed')
        running_seen |= status['lifecycle'] == 'running'
        if status['healthy']:
            need(index == len(readbacks) - 1, 'observations continued after successful readiness')
        last_status = status
    need(same(readbacks[-1].get('status'), last_status) and last_status is not None
         and last_status['lifecycle'] == 'running' and last_status['healthy'] is True,
         'final original healthy Running6 readback required')
    need(same(final['result'], {'state': 'ready', 'status': last_status})
         and same(service, last_status), 'final/source-service status identity')


def verify_start_observation(root):
    """Return hashes after semantic checks, preserving partial hashes on rejection."""
    hashes, documents, errors = {}, {}, []
    root = Path(root).absolute()
    for name in FILES:
        try:
            path = root / name
            need(path.is_file() and not path.is_symlink() and path.resolve() == path,
                 'canonical regular evidence file required')
            with path.open('rb') as handle:
                raw = handle.read(JSON_LIMIT + 1)
            need(0 < len(raw) <= JSON_LIMIT, 'evidence byte bound')
            hashes[name] = hashlib.sha256(raw).hexdigest()
            def nonfinite(_):
                raise ValueError('nonfinite JSON value')
            documents[name] = json.loads(raw, object_pairs_hook=unique, parse_constant=nonfinite)
            need(type(documents[name]) is dict, 'JSON evidence object required')
        except (OSError, ValueError, TypeError, RecursionError) as error:
            errors.append(f'{name}: {error}')
    try:
        need(not errors, '; '.join(errors))
        verify_documents(documents)
    except (KeyError, ValueError, TypeError, AttributeError, RecursionError) as error:
        raise StartObservationError(str(error), hashes) from error
    return {'schema': 'hepta.ordinary-source-start-reader.v1', 'state': 'verified',
            'artifact_sha256': hashes,
            'scope': 'retained one-Start owner readback only; no native count or authority issued'}
