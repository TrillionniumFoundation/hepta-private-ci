#!/usr/bin/env python3
"""Preserve the complete boundary gate and classify the frozen v4 selector inputs."""
from collections import Counter
from pathlib import Path
import re
from . import word_cases as previous
from .transport import binding, sha256

EXPECTED_SOURCE = '36e347f329d061af2e6f45fbd7f0897b3c0a870a54b3d05090b335bfbce72ef5'

def functions(text):
    found = re.findall(r'(?ms)^fn ([^(]+)\(.*?^end\n', text)
    spans = list(re.finditer(r'(?ms)^fn ([^(]+)\(.*?^end\n', text))
    assert len(found) == len(set(found)) == 48
    return {x.group(1): x.group(0) for x in spans}

def choice(value):
    if len(value) < 32:
        return 'original_short'
    if b'\r' not in value[:32] and b'\n' not in value[:32]:
        return 'original_prefix_without_separator'
    return 'count_kernel_prefix_with_separator'

def verify(args, native, report):
    assert sha256(args.source) == EXPECTED_SOURCE
    new_functions = functions(args.source.read_text())
    scan = new_functions['scan_lines']
    expected = '''block count_only(count_only_source:readbuf,count_only_work:mutbuf,count_only_start:u64,count_only_end:u64,count_only_base_index:u64,count_only_emit:bool)
  value_26:u64 = int.sub.checked(count_only_end,count_only_start)
  constant_27:u64 = const() {"value":32}
  value_28:bool = compare.lt(value_26,constant_27)
  constant_29:u64 = const() {"value":0}
  branch value_28 loop(count_only_source,count_only_work,count_only_start,count_only_end,count_only_base_index,count_only_emit,constant_29) count_probe(count_only_source,count_only_work,count_only_start,count_only_end,count_only_base_index,count_only_emit)
block count_probe(count_probe_source:readbuf,count_probe_work:mutbuf,count_probe_start:u64,count_probe_end:u64,count_probe_base_index:u64,count_probe_emit:bool)
  constant_30:u64 = const() {"value":32}
  value_31:u64 = int.add.checked(count_probe_start,constant_30)
  find_ending_32:u64 = call(count_probe_source,count_probe_start,value_31) {"function":"find_ending"}
  value_33:bool = compare.eq(find_ending_32,value_31)
  constant_34:u64 = const() {"value":0}
  branch value_33 loop(count_probe_source,count_probe_work,count_probe_start,count_probe_end,count_probe_base_index,count_probe_emit,constant_34) count_kernel(count_probe_source,count_probe_start,count_probe_end)
block count_kernel(count_kernel_source:readbuf,count_kernel_start:u64,count_kernel_end:u64)
  count_lines_35:u64 = call(count_kernel_source,count_kernel_start,count_kernel_end) {"function":"count_lines"}
  ret(count_lines_35)
end
'''
    assert scan[scan.index('block count_only('):] == expected
    assert 'branch entry_emit loop(entry_source,entry_work,entry_start,entry_end,entry_base_index,entry_emit,constant_1) count_only(entry_source,entry_work,entry_start,entry_end,entry_base_index,entry_emit)' in scan
    inherited = Path(previous.__file__)
    before = binding(inherited)
    previous.verify(args, native, report)
    assert binding(inherited) == before
    halves = {'old': Counter(), 'new': Counter()}
    pairs, edge = Counter(), Counter()
    cases = previous.make_cases()
    assert len(cases) == report['case_count']
    for case in cases:
        old_bytes, new_bytes = case['old'].encode(), case['new'].encode()
        for label, value in (('old', old_bytes), ('new', new_bytes)):
            halves[label][choice(value)] += 1
            edge[label + '_length_31'] += len(value) == 31
            edge[label + '_length_32'] += len(value) == 32
            edge[label + '_length_33'] += len(value) == 33
            edge[label + '_cr_at_prefix_last_byte'] += len(value) >= 32 and value[31] == 13
            edge[label + '_crlf_crosses_prefix'] += len(value) >= 33 and value[31:33] == b'\r\n'
            edge[label + '_first_separator_at_32'] += len(value) > 32 and b'\r' not in value[:32] and b'\n' not in value[:32] and value[32] in (10, 13)
            edge[label + '_no_prefix_separator_but_later_separator'] += len(value) > 32 and b'\r' not in value[:32] and b'\n' not in value[:32] and (b'\r' in value[32:] or b'\n' in value[32:])
        pairs[choice(old_bytes) + ' / ' + choice(new_bytes)] += 1
    wanted = {'original_short', 'original_prefix_without_separator', 'count_kernel_prefix_with_separator'}
    assert all(set(halves[label]) == wanted and all(halves[label].values()) for label in halves)
    assert set(pairs).issuperset({name + ' / ' + name for name in wanted}) and all(pairs.values())
    assert all(edge.values())
    report['inherited_boundary_gate'] = before
    report['selector_static_review'] = {
        'current': binding(args.source),
        'complete_final_source_sha256': EXPECTED_SOURCE,
        'complete_final_function_count': len(new_functions),
        'historical_v3_delta_reexecuted': False,
        'historical_v4_qualification_sha256': '1b81ebc692abc783c348fc4fd082382f1759541d25e23696130cea0f5a02f135',
        'selection_suffix_exact_match': True,
        'bounded_prefix_reasoning': 'The add start+32 is reached only after end-start>=32; the prefix is inside each independently admitted half. Exact find_ending examines [start,start+32). A CR at byte31 selects the unchanged kernel for the entire half. With no prefix separator the original complete scan still processes all later delimiters.'
    }
    report['selector_fixture_coverage'] = {
        'scope': 'Conditions of executed full-interface fixtures under the reviewed exact source; no runtime branch instrumentation or performance claim.',
        'case_count': len(cases), 'per_half': {key: dict(value) for key,value in halves.items()},
        'paired_conditions': dict(pairs), 'prefix_edges': dict(edge),
        'runtime_branch_counts_measured': False,
    }
