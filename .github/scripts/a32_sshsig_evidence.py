"""Pure, fail-closed native census/result reconciliation (no command execution)."""
import hashlib
import json
from pathlib import Path
import re
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET


def require(value, message):
    if not value:
        raise RuntimeError(message)


def digest(data):
    return hashlib.sha256(data).hexdigest()


def census(data, package, allowed_ignored):
    document = json.loads(data)
    cases = {}
    for binary, suite in document['rust-suites'].items():
        require(suite['package-name'] == package and suite.get('status', 'listed') == 'listed',
                'unexpected package or skipped suite in compiled census')
        for name, item in suite['testcases'].items():
            key = binary + ' ' + name
            require(key not in cases and type(item['ignored']) is bool, 'duplicate or invalid census case')
            match = item.get('filter-match', {}).get('status')
            require(match == 'matches' or (item['ignored'] and match == 'mismatch'),
                    'compiled census contains a non-ignored filtered test')
            cases[key] = item['ignored']
    require(cases and len(cases) == document['test-count'], 'empty/inconsistent compiled test census')
    require({x for x, ignored in cases.items() if ignored} == set(allowed_ignored),
            'ignored cases differ from exact reviewed original allowlist')
    return cases


def reconcile_nextest(output, expected):
    text = output.decode('utf-8', 'replace')
    summaries = list(re.finditer(r'(?m)^\s*Summary \[[^\]]+\] (\d+) tests run: (.+)$', text))
    require(len(summaries) == 1, 'missing/repeated nextest terminal summary')
    summary = summaries[0]
    require(re.fullmatch(r'\d+ passed(?:, \d+ skipped)?', summary[2]), 'unrecognized nextest summary outcome')
    counts = {kind: int(number) for number, kind in re.findall(r'(\d+) (passed|failed|skipped)', summary[2])}
    require(not counts.get('failed', 0) and counts.get('passed', 0) == int(summary[1]), 'nextest failures or count mismatch')
    blocks = [text[:summary.start()], text[summary.end():]]
    parsed = []
    for block in blocks:
        cases = {}
        for status, key in re.findall(r'(?m)^\s*(PASS|SKIP|FAIL|TIMEOUT|LEAK|XFAIL|XPASS|TRY \d+|RETRY \d+)\s+\[[^\]]*\]\s+(\S+ .+?)\s*$', block):
            require(key not in cases, 'duplicate attempt/case in nextest status block')
            require(status in ('PASS', 'SKIP'), 'nonpassing/retried nextest result')
            cases[key] = status
        require(set(cases) == set(expected), 'compiled census vs executed status set mismatch')
        require(all((status == 'SKIP') == expected[key] for key, status in cases.items()), 'unexpected ignored/pass classification')
        parsed.append(cases)
    require(parsed[0] == parsed[1], 'live/final nextest statuses disagree')
    require(counts.get('passed', 0) == sum(not value for value in expected.values())
            and counts.get('skipped', 0) == sum(expected.values()), 'nextest summary differs from exact cases')
    return {'compiled_cases': len(expected), 'passed': counts['passed'], 'skipped': counts.get('skipped', 0), 'cases': parsed[0]}


def parse_libtest(data):
    lines = data.decode('utf-8', 'replace').splitlines()
    starts = [(i, re.fullmatch(r'running (\d+) tests?', line)) for i, line in enumerate(lines) if line.startswith('running ')]
    ends = [(i, re.fullmatch(r'test result: (ok|FAILED)\. (\d+) passed; (\d+) failed; (\d+) ignored; (\d+) measured; (\d+) filtered out; finished in (\d+(?:\.\d+)?)s', line)) for i, line in enumerate(lines) if line.startswith('test result:')]
    require(len(starts) == len(ends) == 1 and starts[0][1] and ends[0][1] and starts[0][0] < ends[0][0], 'incomplete libtest suite boundaries')
    begin, running = starts[0]; end, final = ends[0]
    cases = {}; counts = dict(zip(('passed', 'failed', 'ignored', 'measured', 'filtered'), map(int, final.groups()[1:6])))
    listed = dict.fromkeys(('passed', 'failed', 'ignored', 'measured'), 0)
    for i, line in enumerate(lines):
        if not line.startswith('test ') or line.startswith('test result:'):
            continue
        match = re.fullmatch(r'test (.+?) \.\.\. (ok|FAILED|ignored(?:, .+)?|bench: .+)', line)
        require(begin < i < end and match is not None, 'incomplete/out-of-suite libtest case')
        name, status = match.groups()
        require(name not in cases, 'duplicate libtest case')
        kind = 'passed' if status == 'ok' else 'failed' if status == 'FAILED' else 'ignored' if status.startswith('ignored') else 'measured'
        cases[name] = kind; listed[kind] += 1
    require(listed == {k: counts[k] for k in listed} and int(running.group(1)) == len(cases), 'libtest cases/totals disagree')
    require(final.group(1) == 'ok' and not counts['failed'] and not counts['measured'], 'nonpassing libtest suite')
    return {'cases': cases, 'counts': counts}


def parse_libtest_batches(data):
    lines = data.decode('utf-8', 'replace').splitlines()
    ranges = []; start = None
    for index, line in enumerate(lines):
        if line.startswith('running '):
            require(start is None, 'overlapping libtest batch')
            start = index
        elif line.startswith('test result:'):
            require(start is not None, 'libtest result without batch')
            ranges.append((start, index)); start = None
        elif line.startswith('test '):
            require(start is not None, 'case outside libtest batch')
    require(ranges and start is None, 'missing/incomplete libtest batch')
    cases = {}; batches = []
    for start, end in ranges:
        batch = parse_libtest(('\n'.join(lines[start:end + 1]) + '\n').encode())
        require(not set(cases).intersection(batch['cases']), 'same test repeated across libtest batches')
        cases.update(batch['cases']); batches.append(batch)
    return {'cases': cases, 'batches': batches}


def parse_libtest_list(data):
    text = data.decode('utf-8', 'replace')
    found = re.findall(r'(?m)^(.+): test$', text)
    require(found and len(found) == len(set(found)), 'missing/duplicate compiled Bazel case list')
    totals = re.findall(r'(?m)^(\d+) tests?, (\d+) benchmarks?$', text)
    require(len(totals) == 1 and int(totals[0][0]) == len(found) and int(totals[0][1]) == 0, 'Bazel list totals disagree')
    return set(found)


def proto_int(mapping, key):
    value = mapping.get(key, 0)
    require(type(value) is int and value >= 0, 'invalid BEP integer: ' + key)
    return value


def bep_events(data, process_exit, command, allow_no_build=False):
    events = [json.loads(line) for line in data.decode().splitlines()]
    require(events and events[-1].get('lastMessage') is True
            and sum(e.get('lastMessage') is True for e in events) == 1, 'incomplete/repeated BEP terminal')
    ids = [json.dumps(e['id'], sort_keys=True) for e in events]
    require(len(ids) == len(set(ids)), 'duplicate BEP identity')
    by_id = dict(zip(ids, events)); start = json.dumps({'started': {}}, sort_keys=True)
    require(start in by_id, 'missing BEP start')
    started = by_id[start].get('started', {})
    require(started.get('command') == command and started.get('buildToolVersion') == '9.3.0', 'wrong BEP command/tool')
    pending = [start]; reached = set()
    while pending:
        key = pending.pop()
        if key in reached:
            continue
        require(key in by_id, 'announced BEP child missing')
        reached.add(key)
        pending.extend(json.dumps(x, sort_keys=True) for x in by_id[key].get('children', []))
    require(reached == set(ids), 'unlinked BEP work')
    require(not allow_no_build or command == 'build', 'NO_BUILD exemption is analysis-only')
    require(all(allow_no_build and e['aborted'].get('reason') == 'NO_BUILD'
                for e in events if 'aborted' in e), 'unexpected aborted BEP work')
    end = [e['finished'] for e in events if 'buildFinished' in e['id'] and 'finished' in e]
    require(process_exit == 0 and len(end) == 1 and end[0].get('exitCode', {}).get('name') == 'SUCCESS'
            and proto_int(end[0]['exitCode'], 'code') == 0, 'process/BEP outcome mismatch')
    return events


def local_output(item, testlogs_root):
    uri = urllib.parse.urlparse(item.get('uri', ''))
    require(uri.scheme == 'file' and not uri.netloc and not uri.query and not uri.fragment, 'nonlocal BEP output')
    path = Path(urllib.request.url2pathname(uri.path)).resolve()
    require(path.is_relative_to(testlogs_root.resolve()) and path.is_file(), 'BEP output escapes native testlogs')
    data = path.read_bytes()
    require(len(data) <= 100 * 1024 * 1024, 'unbounded test output')
    if 'length' in item:
        require(str(item['length']) == str(len(data)), 'BEP output length differs')
    if item.get('digest'):
        require(item['digest'] == digest(data), 'BEP output digest differs')
    return path, data


def check_xml(data):
    root = ET.fromstring(data)
    suites = [root] if root.tag == 'testsuite' else list(root.findall('testsuite'))
    require(suites, 'test.xml has no test suite')
    total = 0
    for suite in suites:
        cases = suite.findall('testcase'); total += len(cases)
        require(int(suite.get('tests', '-1')) == len(cases), 'XML cases/summary disagree')
        require(int(suite.get('failures', '0')) == int(suite.get('errors', '0')) == 0
                and not any(case.find('failure') is not None or case.find('error') is not None for case in cases), 'XML reports test failure')
        require(int(suite.get('skipped', '0')) == sum(case.find('skipped') is not None for case in cases), 'XML skipped count differs')
    require(total > 0, 'XML has zero wrapper cases')
    return {'xml_cases': total, 'note': 'Bazel wrapper XML count is not asserted equal to native Rust cases'}


def reconcile_bazel(data, process_exit, targets, testlogs_root, destination, expected=None, ignored=()):
    events = bep_events(data, process_exit, 'test')
    results = {}; summaries = {}
    for event in events:
        if 'testResult' in event['id']:
            key = event['id']['testResult']; label = key['label']
            require(label in targets and 'testResult' in event, 'unexpected BEP test target')
            results.setdefault(label, []).append((key, event['testResult']))
        if 'testSummary' in event['id']:
            key = event['id']['testSummary']; label = key['label']
            require(label in targets and label not in summaries and 'testSummary' in event, 'unexpected/duplicate BEP summary')
            summaries[label] = (key, event['testSummary'])
    require(set(results) == set(summaries) == set(targets), 'missing native Bazel owner')
    receipt = {}; discovered = {}
    for label in targets:
        summary_id, summary = summaries[label]
        shards = max(1, proto_int(summary, 'shardCount'))
        require(summary.get('overallStatus') == 'PASSED' and proto_int(summary, 'totalNumCached') == 0
                and proto_int(summary, 'runCount') == proto_int(summary, 'attemptCount') == 1
                and proto_int(summary, 'totalRunCount') == shards, 'cached/retried/incomplete Bazel summary')
        require(len(results[label]) == shards, 'wrong number of native shards')
        require(len(summary.get('passed', [])) == shards and not summary.get('failed'), 'missing/ambiguous summary log references')
        summary_logs = {local_output(x, testlogs_root)[0] for x in summary['passed']}
        require(len(summary_logs) == shards, 'duplicate summary log reference')
        actual_logs = set()
        seen_shards = set(); cases = {}; union = set(); records = []
        for identity, result in results[label]:
            shard = proto_int(identity, 'shard')
            require(proto_int(identity, 'run') == proto_int(identity, 'attempt') == 1 and shard not in seen_shards
                    and identity.get('configuration') and identity.get('configuration') == summary_id.get('configuration'), 'retried/duplicate/config-mismatched native shard')
            seen_shards.add(shard)
            info = result.get('executionInfo', {})
            require(result.get('status') == 'PASSED' and result.get('cachedLocally', False) is False
                    and info.get('cachedRemotely', False) is False and proto_int(info, 'exitCode') == 0
                    and info.get('strategy') in ('local', 'standalone', 'sandboxed', 'linux-sandbox', 'windows-sandbox'), 'non-native/cached/failing test action')
            output_items = result.get('testActionOutput', [])
            outputs = {x.get('name'): x for x in output_items}
            require(len(outputs) == len(output_items), 'ambiguous repeated test output name')
            require('test.log' in outputs and 'test.xml' in outputs, 'missing native log/XML')
            folder = destination / digest(label.encode())[:16] / f'shard-{shard}'
            folder.mkdir(parents=True, exist_ok=False)
            log_path, log = local_output(outputs['test.log'], testlogs_root)
            require(log_path not in actual_logs, 'same physical log reused across shards')
            actual_logs.add(log_path)
            _, xml = local_output(outputs['test.xml'], testlogs_root)
            (folder / 'test.log').write_bytes(log); (folder / 'test.xml').write_bytes(xml)
            xml_result = check_xml(xml)
            if expected is None:
                union.update(parse_libtest_list(log))
            else:
                batch_result = parse_libtest_batches(log)
                result_cases = batch_result['cases']
                require(all(batch['counts']['filtered'] + len(batch['cases']) == len(expected[label])
                            for batch in batch_result['batches']), 'batch filtered/compiled counts disagree')
                require(not set(cases).intersection(result_cases), 'same native case executed in multiple shards')
                cases.update(result_cases)
            records.append({'identity': identity, 'result': result, 'xml': xml_result,
                            'log_sha256': digest(log), 'xml_sha256': digest(xml)})
        require(seen_shards == set(range(1, shards + 1)), 'missing native shard index')
        require(summary_logs == actual_logs, 'result and summary refer to different native logs')
        if expected is not None:
            require(set(cases) == set(expected[label]), 'compiled Bazel census differs from full native case union')
            require({name for name, status in cases.items() if status == 'ignored'} == set(ignored.get(label, [])), 'unexpected native Bazel ignored cases')
        discovered[label] = sorted(union if expected is None else cases)
        receipt[label] = {'summary': summary, 'shards': records, 'native_cases': len(discovered[label]), 'cases': cases}
    return {'targets': receipt, 'compiled_cases': discovered, 'all_announced_events_completed': True}
