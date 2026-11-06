#!/usr/bin/env python3
"""Offline test-spawn associations, explicitly retaining compact retry-digest reuse."""
import collections
import hashlib
import json
from pathlib import Path
import re
import sys
import xml.etree.ElementTree as ET
sys.dont_write_bytecode = True
ROOT = Path(__file__).resolve().parent


def identity(data):
    return {'bytes': len(data), 'git_blob': hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest(), 'sha256': hashlib.sha256(data).hexdigest()}


def norm(path):
    return path.replace('\\', '/')


def env(spawn):
    values = {e['name']: e['value'] for e in spawn['env_vars']}
    assert len(values) == len(spawn['env_vars'])
    return values


def main():
    source = (ROOT / 'borrowed/decode_compact.py').read_bytes()
    assert identity(source)['git_blob'] == 'bb0957782c73a2a653e101e392da5f0f27ed4459'
    old = '    print(json.dumps(summary,ensure_ascii=False,indent=2))\n'
    new = '    return summary, entries, spawns\n'
    assert source.decode().count(old) == 1
    adapted = source.decode().replace(old, new)
    assert adapted.replace(new, old).encode() == source
    result = []
    projections = []
    for label in ['shard4', 'shard2']:
        namespace = {'__file__': str(ROOT / 'borrowed/decode_compact.py'), '__name__': 'fixed_decoder_return_only'}
        exec(compile(adapted, '<fixed decoder with return-only adapter>', 'exec'), namespace)
        artifacts = ROOT / 'artifacts' / ('windows-' + label + '-original')
        compact = list(artifacts.glob('*.zst'))
        assert len(compact) == 1
        work = ROOT / ('compact-' + label)
        namespace['ROOT'] = work
        namespace['COMPACT'] = compact[0]
        summary, entries, spawns = namespace['decode']()
        assert (json.dumps(summary, ensure_ascii=False, indent=2) + '\n').encode() == (work / 'decoder.stdout.json').read_bytes()
        wanted = {'//codex-rs/core:core-all-test', '//codex-rs/windows-sandbox-rs:windows-sandbox-rs-unit-tests'}
        tests = [s for s in spawns if s['mnemonic'] == 'TestRunner' and s['target_label'] in wanted]
        tws = [s for s in tests if norm(s['args'][0]).endswith('/tw.exe')]
        xmls = [s for s in tests if norm(s['args'][0]).endswith('/xml.exe')]
        assert len(tws) == len(xmls) == (19 if label == 'shard4' else 1)
        manifest_paths = list((artifacts / 'failed-test-logs').glob('*/manifest.json'))
        assert len(manifest_paths) == 1
        manifest_path = manifest_paths[0]
        manifest = json.loads(manifest_path.read_bytes())
        assert manifest['complete_for_selected_targets'] and not manifest['errors']
        retained = {}
        for item in manifest['files']:
            key = (item['target'], item['testlogs_relative_path'])
            assert key not in retained
            p = manifest_path.parent / item['archive_relative_path']
            actual = identity(p.read_bytes())
            assert actual['bytes'] == item['bytes'] and actual['sha256'] == item['sha256']
            retained[key] = p
        groups = collections.defaultdict(list)
        for tw in tws:
            groups[(tw['target_label'], norm(env(tw)['XML_OUTPUT_FILE']))].append(tw)
        used = set()
        used_logs = set()
        selected_input_records = {}
        for xml in xmls:
            assert len(xml['args']) == 5 and xml['exit_code'] == 0
            log_path, xml_path = map(norm, xml['args'][1:3])
            candidates = [s for s in groups[(xml['target_label'], xml_path)] if s['sequence'] not in used and s['sequence'] < xml['sequence']]
            assert len(candidates) == 1, (label, xml['sequence'], [s['sequence'] for s in candidates])
            tw = candidates[0]
            used.add(tw['sequence'])
            group = groups[(tw['target_label'], xml_path)]
            ordinal = group.index(tw) + 1
            assert tw['exit_code'] == int(xml['args'][4])
            wall = tw['metrics']['execution_wall_time']
            assert int(xml['args'][3]) == wall['seconds']
            assert tw['runner'] == xml['runner'] == 'local'
            assert tw['cache_hit'] is False and xml['cache_hit'] is False
            assert tw['timeout_millis'] == (900000 if label == 'shard4' else 300000)
            assert xml['timeout_millis'] == 0
            relative = log_path.split('/testlogs/', 1)[1]
            if ordinal < len(group):
                relative = relative.removesuffix('test.log') + f'test_attempts/attempt_{ordinal}.log'
            log_file = retained[(tw['target_label'], relative)]
            xml_file = retained[(tw['target_label'], relative.removesuffix('.log') + '.xml')]
            assert log_file not in used_logs
            used_logs.add(log_file)
            log_identity = identity(log_file.read_bytes())
            xml_identity = identity(xml_file.read_bytes())
            tree = ET.fromstring(xml_file.read_bytes())
            cases = list(tree.iter('testcase'))
            assert len(cases) == 1
            case = cases[0]
            assert case.attrib['duration'] == case.attrib['time'] == xml['args'][3]
            errors = list(case.iter('error')) + list(case.iter('failure'))
            assert bool(errors) == bool(tw['exit_code'])
            raw_text = log_file.read_bytes().decode('utf-8')
            xml_view = ''.join(c if c in '\t\n\r' or ord(c) >= 32 else '?' for c in raw_text).replace('\r\n', '\n').replace('\r', '\n')
            assert tree.find('.//system-out').text == xml_view
            batches = []
            pattern = r'test result: (ok|FAILED)\. (\d+) passed; (\d+) failed; (\d+) ignored; (\d+) measured; (\d+) filtered out; finished in ([0-9.]+)s'
            for m in re.finditer(pattern, raw_text):
                batches.append({'status': m[1], **{k: int(v) for k, v in zip(['passed', 'failed', 'ignored', 'measured', 'filtered_out'], m.groups()[1:6])}, 'duration_seconds_text': m[7]})
            assert batches and bool(sum(b['failed'] for b in batches)) == bool(tw['exit_code'])
            visited = set()
            files = []
            def visit(n):
                if not n or n in visited:
                    return
                assert n in entries
                visited.add(n)
                entry = entries[n]
                selected_input_records[str(n)] = entry
                if entry['type'] == 'file':
                    files.append((n, entry))
                for key in ('input_ids', 'transitive_set_ids'):
                    for child in entry.get(key, []):
                        visit(child)
                for key in ('input_set_id', 'symlinks_id', 'root_symlinks_id'):
                    visit(entry.get(key, 0))
                for child in entry.get('direct_entries', []):
                    visit(child['entry_id'])
            visit(xml['input_set_id'])
            visit(xml['tool_set_id'])
            inputs = [(n, entry) for n, entry in files if norm(entry['path']) == log_path]
            outputs = [entry for entry in xml['outputs'] if entry.get('type') == 'file' and norm(entry['path']) == xml_path]
            assert len(inputs) == len(outputs) == 1
            log_id, log_entry = inputs[0]
            xd = outputs[0]['digest']
            ld = log_entry['digest']
            log_equal = (ld['hash'], ld['size_bytes']) == (log_identity['sha256'], log_identity['bytes'])
            xml_equal = (xd['hash'], xd['size_bytes']) == (xml_identity['sha256'], xml_identity['bytes'])
            assert log_equal == xml_equal
            assert log_equal == (ordinal == 1)
            result.append({'artifact': label, 'target': tw['target_label'], 'actual_tw_sequence': tw['sequence'], 'xml_generator_sequence': xml['sequence'], 'runner': tw['runner'], 'cache_hit': tw['cache_hit'], 'timeout_millis': tw['timeout_millis'], 'original_test_exit': tw['exit_code'], 'xml_generator_original_exit_argument': int(xml['args'][4]), 'xml_generator_duration_seconds': int(xml['args'][3]), 'xml_generator_exit': xml['exit_code'], 'attempt_ordinal_from_same_target_and_output_path': ordinal, 'attempts_for_this_shard': len(group), 'log': str(log_file.relative_to(ROOT)), 'log_identity': log_identity, 'xml': str(xml_file.relative_to(ROOT)), 'xml_identity': xml_identity, 'retention_manifest': str(manifest_path.relative_to(ROOT)), 'log_input_entry_id': log_id, 'recorded_log_input_digest': ld, 'xml_output_entry_id': outputs[0]['entry_id'], 'recorded_xml_output_digest': xd, 'compact_file_digest_equals_this_attempt': log_equal, 'original_log_equals_XML_system_out_after_XML_control_filtering': True, 'XML_duration_and_status_match_spawn': True, 'libtest_batches': batches, 'failure_headers': re.findall(r'^---- (.+) stdout ----$', raw_text, re.M), 'binding': 'Same target/output path and unique sequential tw/XML pair; exact original exit/duration and retained attempt ordinal/name agree. Full XML transcript equals raw log after XML control filtering. Compact file digests are only current for the first attempt; subsequent records reuse path IDs and must not be called fresh per-attempt hash evidence.'})
        assert len(used) == len(used_logs) == len(tws)
        out = work / 'xml-input-relationships.v2.json'
        out.write_text(json.dumps(selected_input_records, ensure_ascii=False, indent=2) + '\n')
        projections.append({'artifact': label, 'entries': len(selected_input_records), 'file': str(out.relative_to(ROOT)), 'identity': identity(out.read_bytes())})
    assert len(result) == 20
    assert sum(x['compact_file_digest_equals_this_attempt'] for x in result) == 17
    library = [x for x in result if x['artifact'] == 'shard2']
    assert len(library) == 1 and library[0]['compact_file_digest_equals_this_attempt']
    for case in ['typed_setup_report_preserves_code_and_message_through_context', 'untyped_setup_report_preserves_context_chain_and_os_error']:
        text = (ROOT / library[0]['log']).read_text()
        assert text.count('test setup_error::tests::' + case + ' ... ok') == 1
    receipt = {'schema': 'windows-setup-causes-actual-test-associations-v2', 'bindings': result, 'input_projections': projections, 'decoder_original': identity(source), 'return_only_adapter': identity(adapted.encode()), 'original_parser_and_record_handling_unchanged': True, 'test_execution_performed': False, 'limits': ['Three retried Core records reuse first-attempt file digest IDs in original compact. No per-retry fresh digest claim.', 'Original artifact names, manifest hashes, exact XML transcript/status/duration and ordered spawn records associate all nineteen Core attempts; XML generator spawns are not tests.', 'Two new setup error-report cases pass only in the uniquely bound local noncached Windows library execution; its overall target still fails.']}
    (ROOT / 'actual-test-runner-bindings.v2.json').write_text(json.dumps(receipt, ensure_ascii=False, indent=2) + '\n')
    print(json.dumps({'bindings': len(result), 'core_attempts': 19, 'windows_library_attempts': 1, 'all_actual_tw_local_noncached': True, 'first_or_single_attempt_digest_equal': 17, 'retry_records_reusing_old_digest': 3, 'library': library}, ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()
