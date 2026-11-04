"""Only download pinned evidence and parse ZIP/JSON/logs; no artifact code or ELF is executed."""
import ast, datetime, hashlib, json, os, re, signal, stat, sys, types, urllib.parse, urllib.request, zipfile
from pathlib import Path, PurePosixPath
ROOT=None
H='103e4bcb3a6fbce57943a0c7c339d1d48808ce69'; M='68c36639d609033334785b347273899f5abab500'
T='73d6f50dd52b5e30b536758335dbc82385f63ab3'; B='3a81000aae08c658276958d678874aca4db5eedd'
S='bb813345a214c52767ac544230d6a475d51e8509'; W='9dcf16372805fa13840875e396da579f16236c6f32524465eca4425d2a4bfe24'
RUN=41746794500
def sha(data):return hashlib.sha256(data).hexdigest()
def write(path,value):
 with path.open('w') as f:json.dump(value,f,indent=2);f.write('\n');f.flush();os.fsync(f.fileno())
def extract(marker,expected):
 raw=(ROOT/'published-workflow.yml').read_bytes();assert len(raw)==115861 and sha(raw)==W
 pattern=r"(?m)^( +)[^\n]*<<'"+marker+r"'\n([\s\S]*?)^\1"+marker+r"\s*$"
 values=[]
 for match in re.finditer(pattern,raw.decode()):
  indent,body=match.groups(); lines=[]
  for line in body.splitlines(True):
   assert line.startswith(indent) or not line.strip()
   lines.append(line[len(indent):] if line.startswith(indent) else line)
  code=''.join(lines);assert sha(code.encode())==expected,(marker,sha(code.encode()))
  values.append(code)
 assert values and len(set(values))==1
 return values[0]

# Pure reader functions frozen from the separately fetched, SHA-pinned workflow.
# Runtime never compiles, imports, evals, or executes data-root script contents.
HELPER = '//codex-rs/exec-server:codex-exec-server-test-helper'

HELPER_SOURCE = 'codex-rs/exec-server/examples/codex-exec-server-test-helper.rs'

HELPER_NAME = 'codex-exec-server-test-helper'

ROOT_SOURCES = {'exec_discovery': 'codex-rs/exec-server/tests/capability_discovery.rs',
                'exec_fs': 'codex-rs/exec-server/tests/file_system_unix.rs'}

FORMATTER = '''def file_record(f):
    return {"path": f.path, "short_path": f.short_path, "owner": str(f.owner)}
def selected_runfiles(runfiles):
    if runfiles == None:
        return []
    return [file_record(f) for f in runfiles.files.to_list() if f.basename == "codex-exec-server-test-helper"]
def format(target):
    available = providers(target)
    info = available["DefaultInfo"]
    run_env = available.get("RunEnvironmentInfo")
    environment = None if run_env == None else {"helper": run_env.environment.get("CARGO_BIN_EXE_codex-exec-server-test-helper"), "inherited": run_env.inherited_environment}
    return json.encode({"label": str(target.label), "files": [file_record(f) for f in info.files.to_list()], "default_runfiles": selected_runfiles(info.default_runfiles), "data_runfiles": selected_runfiles(info.data_runfiles), "run_environment": environment})
'''

RUNFILE_ENV='CARGO_BIN_EXE_'+HELPER_NAME

def normalized_label(label):
    # Only normalize the main repository spellings. Never strip an external name.
    for prefix in ('@@//', '@//'):
        if label.startswith(prefix):
            return '//' + label[len(prefix):]
    return label

def feature_values(vector):
    features = []
    for index, argument in enumerate(vector):
        value = argument[len('--cfg='):] if argument.startswith('--cfg=') else (
            argument if index and vector[index - 1] == '--cfg' else '')
        match = re.fullmatch(r'feature="([^"]+)"', value)
        if match:
            features.append(match.group(1))
    return features

def rustc_command_arguments(action):
    arguments = action.get('arguments', [])
    assert arguments and all(isinstance(value, str) for value in arguments), 'missing action arguments'
    parameters = {}
    for parameter in action.get('paramFiles', []):
        path = parameter.get('execPath')
        values = parameter.get('arguments', [])
        assert isinstance(path, str) and path and path not in parameters, 'missing or duplicate parameter-file identity'
        assert isinstance(values, list) and all(isinstance(value, str) for value in values)
        parameters[path] = values
    consumed = {}

    def consume(path, role):
        assert path in parameters, 'referenced parameter file is absent from aquery: ' + path
        previous = consumed.get(path)
        assert previous is None or previous['role'] == role, 'parameter file reused across wrapper and Rustc roles'
        consumed[path] = {'role': role, 'references': 1 if previous is None else previous['references'] + 1}
        return parameters[path]

    # The pinned wrapper patch expands only argv[1], once. Its values are
    # literal, including values beginning with @ or --wrapper-args=.
    expanded = list(arguments)
    if len(expanded) > 1 and expanded[1].startswith('--wrapper-args='):
        wrapper_path = expanded[1][len('--wrapper-args='):]
        wrapper_arguments = consume(wrapper_path, 'wrapper')
        assert '--' not in wrapper_arguments, 'wrapper response file contains the child boundary'
        expanded = [expanded[0], *wrapper_arguments, *expanded[2:]]
    basename = lambda value: value.replace('\\', '/').rsplit('/', 1)[-1]
    assert basename(expanded[0]) in ('process_wrapper', 'process_wrapper.exe'), 'expected the pinned process wrapper'
    assert '--' in expanded, 'missing wrapper/child boundary'
    boundary = expanded.index('--')
    wrapper = expanded[1:boundary]
    wrapper_flags = {
        '--subst', '--stable-status-file', '--volatile-status-file', '--env-file',
        '--out-dir', '--arg-file', '--touch-file', '--copy-output', '--stdout-file',
        '--stderr-file', '--captured-exit-code-file', '--output-file',
        '--rustc-output-format', '--require-explicit-unstable-features',
    }
    link_search_files = []
    index = 0
    while index < len(wrapper):
        flag = wrapper[index]
        assert flag in wrapper_flags and index + 1 < len(wrapper), 'unexpected or incomplete wrapper option'
        value = wrapper[index + 1]
        if flag == '--arg-file':
            # These seven roots have no build.rs or lint-config input. The
            # pinned rule propagates only dependency .linksearchpaths here;
            # the pinned producer writes -L entries, not feature cfg flags.
            assert value.endswith('.linksearchpaths'), 'uninspected dynamic compiler-flags input'
            if value in parameters:
                assert all(item.startswith('-L') for item in consume(value, 'link-search')), 'link-search input contains non-link arguments'
            link_search_files.append({'path': value, 'included_in_param_files': value in parameters})
        index += 2
    child = expanded[boundary + 1:]
    assert child and basename(child[0]) in ('rustc', 'rustc.exe'), 'expected an actual Rustc child command'

    def expand_rustc(vector, stack=()):
        result = []
        for argument in vector:
            if argument.startswith('@'):
                path = argument[1:]
                assert path not in stack, 'cyclic Rustc parameter-file reference'
                result.extend(expand_rustc(consume(path, 'rustc'), (*stack, path)))
            else:
                result.append(argument)
        return result

    rustc_arguments = expand_rustc(child[1:])
    assert '--' not in rustc_arguments, 'unexpected Rustc option terminator'
    assert set(consumed) == set(parameters), 'aquery contains an unreferenced parameter file'
    return {'rustc_executable': child[0], 'rustc_arguments': rustc_arguments,
        'parameter_files': [{'exec_path': path, 'argument_count': len(parameters[path]), **consumed[path]}
                            for path in sorted(parameters)],
        'dependency_link_search_files': link_search_files}

def inspect_actions(graph, expected):
    targets = {str(item['id']): normalized_label(item['label']) for item in graph.get('targets', [])}
    configurations = {str(item['id']): item for item in graph.get('configuration', [])}
    observed = []
    for action in graph.get('actions', []):
        label = targets.get(str(action.get('targetId')))
        assert action.get('mnemonic') == 'Rustc' and label in expected, 'unexpected configured root action'
        binding = rustc_command_arguments(action)
        arguments = binding['rustc_arguments']
        features = sorted(set(feature_values(arguments)))
        sources = sorted(set(value for value in arguments if value.endswith('.rs')))
        source_suffix = expected[label]['source']
        source_path = arguments[0].replace('\\', '/') if arguments else ''
        source_present = source_path == source_suffix or source_path.endswith('/' + source_suffix)
        configuration = configurations.get(str(action.get('configurationId')), {})
        observed.append({
            'label': label,
            'features': features,
            'expected_features': expected[label]['features'],
            'rustc_sources': sources,
            'expected_source': source_suffix,
            'expected_source_present': source_present,
            'configuration_id': action.get('configurationId'),
            'configuration_checksum': configuration.get('checksum'),
            'configuration_mnemonic': configuration.get('mnemonic'),
            'configuration_is_tool': configuration.get('isTool', False),
            'execution_platform': action.get('executionPlatform'),
            'rustc_executable': binding['rustc_executable'],
            'parameter_files': binding['parameter_files'],
            'dependency_link_search_files': binding['dependency_link_search_files'],
            'feature_source': 'expanded configured Rustc child argv; dependency link-search files recorded separately',
            'rustc_argument_vector_sha256': hashlib.sha256(json.dumps(arguments, separators=(',', ':')).encode()).hexdigest(),
        })
    return observed

def validate_actions(observed, expected):
    assert {item['label'] for item in observed} == set(expected), 'all seven root labels must have an actual Rustc action'
    assert all(item['features'] == item['expected_features'] for item in observed), 'configured feature closure differs'
    assert all(item['expected_source_present'] for item in observed), 'configured action did not bind the expected crate source'

def normalize_path(value):
    assert isinstance(value, str) and value and '\\' not in value and '\x00' not in value
    path = PurePosixPath(value)
    assert not path.is_absolute() and '..' not in path.parts and str(path) == value, 'noncanonical relative artifact path'
    assert path.parts[0] == 'bazel-out', 'expected configured Bazel output'
    return value

def unique_map(items, key):
    result = {}
    for item in items:
        ident = str(item[key])
        assert ident not in result, 'duplicate graph identity'
        result[ident] = item
    return result

def environment(action):
    entries = action.get('environmentVariables', [])
    result = {}
    for item in entries:
        assert item['key'] not in result, 'duplicate action environment key'
        result[item['key']] = item['value']
    return result

def option_values(arguments, name):
    result = []
    for index, value in enumerate(arguments):
        if value == name:
            assert index + 1 < len(arguments), 'missing option value'
            result.append(arguments[index + 1])
        elif value.startswith(name + '='):
            result.append(value[len(name) + 1:])
    return result

def one_option(arguments, name):
    values = option_values(arguments, name)
    assert len(values) == 1, 'expected one ' + name
    return values[0]

def profile(arguments):
    values = option_values(arguments, '--codegen') + option_values(arguments, '-C')
    values += [v[2:] for v in arguments if v.startswith('-C') and v != '-C' and not v.startswith('-C=')]
    result = {}
    for key in ('opt-level', 'debuginfo', 'debug-assertions', 'strip'):
        found = [v.split('=', 1)[1] for v in values if v.startswith(key + '=')]
        assert len(found) <= 1, 'ambiguous codegen setting'
        result[key] = found[0] if found else None
    assert result['opt-level'] is not None
    return result

def inspect_graph(graph, case, triple, parser):
    targets = unique_map(graph.get('targets', []), 'id')
    configs = unique_map(graph.get('configuration', []), 'id')
    artifacts = unique_map(graph.get('artifacts', []), 'id')
    fragments = unique_map(graph.get('pathFragments', []), 'id')
    def artifact_path(ident):
        artifact = artifacts[str(ident)]
        seen, parts = set(), []
        fragment = str(artifact['pathFragmentId'])
        while fragment != '0':
            assert fragment not in seen, 'cyclic artifact path'
            seen.add(fragment)
            node = fragments[fragment]
            assert isinstance(node['label'], str) and node['label'] and '/' not in node['label']
            parts.append(node['label'])
            fragment = str(node.get('parentId', 0))
        return normalize_path('/'.join(reversed(parts)))
    grouped = {}
    for action in graph.get('actions', []):
        label = parser.normalized_label(targets[str(action['targetId'])]['label'])
        assert label in (case['target'], HELPER), 'unexpected configured target'
        mnemonic = action['mnemonic']
        assert mnemonic in ('Rustc', 'TestRunner'), 'unexpected analysis action'
        grouped.setdefault((label, mnemonic), []).append(action)
    required = {(HELPER, 'Rustc'), (case['target'], 'Rustc'), (case['target'], 'TestRunner')}
    assert set(grouped) == required and all(len(v) == 1 for v in grouped.values()), 'require one normal helper, one test Rustc, and one TestRunner action'
    observed = {}
    for label in (HELPER, case['target']):
        action = grouped[(label, 'Rustc')][0]
        config = configs[str(action['configurationId'])]
        assert config.get('checksum') and not config.get('isTool', False), 'helper/test must use a target configuration'
        binding = parser.rustc_command_arguments(action)
        args = binding['rustc_arguments']
        source = HELPER_SOURCE if label == HELPER else case['source']
        assert args and args[0] == source, 'wrong Rust crate root'
        assert one_option(args, '--target') == triple, 'configured ABI differs'
        assert args.count('--test') == (0 if label == HELPER else 1), 'helper must be ordinary main; original root remains libtest'
        if label == HELPER:
            assert one_option(args, '--crate-type') == 'bin'
            assert one_option(args, '--crate-name') == 'codex_exec_server_test_helper'
        else:
            assert environment(action).get('BAZEL_PACKAGE') == 'codex-rs/exec-server', 'original compiled Bazel dispatch marker missing'
        basename = HELPER_NAME if label == HELPER else case['target'].split(':')[-1]
        outputs = [artifact_path(ident) for ident in action.get('outputIds', [])]
        linked = [path for path in outputs if PurePosixPath(path).name == basename]
        assert len(linked) == 1, 'missing or ambiguous linked executable output'
        observed[label] = {'source': source, 'target_triple': triple, 'is_libtest': '--test' in args,
            'profile': profile(args), 'configuration_id': action['configurationId'],
            'configuration_checksum': config['checksum'], 'output': linked[0],
            'rustc_arguments_sha256': sha(json.dumps(args, separators=(',', ':')).encode()),
            'parameter_files': binding['parameter_files'], 'dependency_link_search_files': binding['dependency_link_search_files']}
    assert observed[HELPER]['profile'] == observed[case['target']]['profile'], 'helper and test codegen profile differ'
    test_action = grouped[(case['target'], 'TestRunner')][0]
    test_config = configs[str(test_action['configurationId'])]
    assert not test_config.get('isTool', False)
    assert test_config['checksum'] == observed[case['target']]['configuration_checksum'], 'TestRunner configuration differs from test Rustc'
    # TestRunnerAction.getEnvironment omits rule-specific extraTestEnv.
    # Bind that declaration via its actual cquery RunEnvironmentInfo below.
    observed['test_runner_configuration_checksum'] = test_config['checksum']
    return observed

def inspect_cquery(raw, case, observed, parser):
    rows = [json.loads(line) for line in raw.decode().splitlines() if line.strip()]
    by_label = {}
    for row in rows:
        label = parser.normalized_label(row['label'])
        assert label not in by_label and label in (case['target'], HELPER), 'ambiguous or unexpected configured cquery target'
        by_label[label] = row
    assert set(by_label) == {case['target'], HELPER}
    for label, row in by_label.items():
        assert len(row['files']) == 1, 'expected one DefaultInfo executable'
        file = row['files'][0]
        assert normalize_path(file['path']) == observed[label]['output']
        assert parser.normalized_label(file['owner']) == label
        short = PurePosixPath(file['short_path'])
        assert not short.is_absolute() and '..' not in short.parts and str(short) == file['short_path']
    helper_file = by_label[HELPER]['files'][0]
    root = by_label[case['target']]
    runfiles = root['default_runfiles'] + root['data_runfiles']
    assert runfiles and all(item == helper_file for item in runfiles), 'test runfiles do not declare exactly this configured helper'
    run_env = root['run_environment']
    assert isinstance(run_env, dict) and isinstance(run_env.get('inherited'), list), 'test RunEnvironmentInfo is absent'
    assert not any(name in run_env['inherited'] for name in (RUNFILE_ENV, RUNFILE_ENV.replace('-', '_'))), 'inherited environment could replace the declared helper'
    assert run_env['helper'] == '_main/' + helper_file['short_path'], 'CARGO_BIN_EXE does not reference the declared runfile'
    return {'test': root['files'][0], 'helper': helper_file,
            'runfile_key': run_env['helper'], 'declared_runfile_occurrences': len(runfiles),
            'run_environment_provider': 'RunEnvironmentInfo', 'inherited_environment_names': run_env['inherited']}

def trusted_readers():
 runner=extract('PYCONTROL','ac157b9d9d3b336bff896e7525ba12b3d706af53e2854bf7a783047a4736deec')
 checker=extract('PYFEATURES','67a5fa23b072ef9250b94020ab1d59c2062c25cdfa1ffb43d12cb8f7a66de187')
 helper=extract('PYEXECPROOF','24350a98ae1d0459e1100b39f978eea9f5c9354f6c77b10a90b4f50773ae4d30')
 values={}
 for node in ast.parse(runner).body:
  if isinstance(node,ast.Assign):
   for target in node.targets:
    if isinstance(target,ast.Name) and target.id in ('cases','case_arguments','expected_timeouts','allowed_groups'):
     values[target.id]=ast.literal_eval(node.value)
 # These functions come only from the independently fetched immutable workflow,
 # verified above. Nothing from a downloaded artifact is compiled or imported.
 parser=types.SimpleNamespace(**{name:globals()[name] for name in ['feature_values', 'inspect_actions', 'normalized_label', 'rustc_command_arguments', 'validate_actions']})
 hns={name:globals()[name] for name in ['FORMATTER', 'HELPER', 'HELPER_NAME', 'HELPER_SOURCE', 'ROOT_SOURCES', 'RUNFILE_ENV', 'environment', 'inspect_cquery', 'inspect_graph', 'normalize_path', 'one_option', 'option_values', 'profile', 'unique_map']}
 return values,runner,checker,helper,parser,hns

def audit(path,metadata,job,kind,platform,group):
 expected,runner,checker,helper,parser,hns=trusted_readers()
 checks=[]
 def ck(name,value):checks.append({'name':name,'ok':bool(value)})
 result={'schema':'hepta-musl-normal140-recovery-audit-v1','scope':'Offline evidence only; no native/retry/artifact code execution','artifact':metadata,'job':job,'kind':kind,'platform':platform,'group':group,'checks':checks,'cases':{},'elf_limit':'CI ELF identity records only; no ELF bytes are contained in these ZIPs or locally rehashed.'}
 data=path.read_bytes();result.update(zip_bytes=len(data),zip_sha256=sha(data))
 ck('official_size_sha',len(data)==metadata['size_in_bytes'] and metadata['digest']=='sha256:'+sha(data))
 ck('terminal_exact_job',job['run_id']==RUN and job['status']=='completed')
 ck('exact_artifact_run_source',metadata['workflow_run']['id']==RUN and metadata['workflow_run']['head_sha']==S)
 ck('exact_artifact_lane',metadata['name']=='normal-bazel-musl-helper-'+group+'-'+kind+'-'+platform+'-'+H)
 selected=H if kind=='head' else M; configured='//:local_linux' if platform=='gnu' else '@rules_rs//rs/platforms:x86_64-unknown-linux-musl'
 with zipfile.ZipFile(path) as z:
  names=z.namelist();ck('CRC',z.testzip() is None)
  ck('safe_unique_members',len(names)==len(set(names)) and all(not n.startswith('/') and '..' not in PurePosixPath(n).parts and '\\' not in n for n in names) and all(not stat.S_ISLNK(i.external_attr>>16) for i in z.infolist()))
  read=z.read
  def obj(name):return json.loads(read(name))
  result['members']={n:{'bytes':len(read(n)),'sha256':sha(read(n))} for n in names if not n.endswith('/')}
  try:
   src=obj('source-before.json');result['source_before']=src
   pins={'tested_commit':selected,'tested_tree':T,'source_kind':kind,'candidate':H,'base':B,'prospective_merge':M,'harness_commit':S,'workflow_sha256':W,'bazel_platform':configured,'normal_group':group,'checkout_fetch_depth':32,'observed_merge_base':B}
   ck('source_pins',all(src.get(k)==v for k,v in pins.items()))
   ck('source_after_clean',read('source-after.txt').decode().splitlines()==[selected,T] and read('source-after-status.txt')==b'')
   ck('unchanged_runner_parser',read('run-target.py').decode()==runner and read('check-features.py').decode()==checker)
   dep=obj('dependency-import.json');result['dependency']=dep
   ck('fixed_dependency',dep.get('artifact_id')==13245890316 and dep.get('bytes')==145542555 and dep.get('sha256')=='a6bf6adfc5f9bba559d28554b7d3581b15f2813f03bc9f2ae19f0d915e97dadf' and dep.get('verified') is True)
  except Exception as error:ck('complete_source_evidence',False);result['source_reader_error']=repr(error)
  for key in expected['allowed_groups'][group]:
   target,binary,wanted=expected['cases'][key];prefix=key+'/';start=len(checks)
   entry={'target':target,'binary_target':binary,'expected_names':wanted};result['cases'][key]=entry
   needed=['command.json','build-events.jsonl','original-test.log','native.exit','binary-identities.json']
   entry['missing']=[n for n in needed if prefix+n not in names];ck(key+':complete_evidence',not entry['missing'])
   if prefix+'result.json' in names:entry['harness_reader']=obj(prefix+'result.json')
   if prefix+'original-test.log' in names:
    text=read(prefix+'original-test.log').decode().replace('\r','')
    seen=re.findall(r'^test ([A-Za-z_][A-Za-z0-9_:]*) \.\.\.',text,re.M)
    running=re.findall(r'^running (\d+) tests?$',text,re.M)
    summaries=re.findall(r'^test result: (ok|FAILED)\. (\d+) passed; (\d+) failed; (\d+) ignored; (\d+) measured; (\d+) filtered out;',text,re.M)
    entry.update(observed_names=seen,running_counts=running,native_summaries=summaries)
    ck(key+':exact_original_names',len(seen)==len(set(seen)) and sorted(seen)==sorted(wanted) and running==[str(len(wanted))])
    ck(key+':no_success_skip',re.search(r'\bskipping test\b',text,re.I) is None)
    ck(key+':one_summary',len(summaries)==1)
    if len(summaries)==1:
     state,p,f,i,m,filtered=summaries[0];entry.update(outcome=state,passed=int(p),failed=int(f),ignored=int(i),measured=int(m),filtered=int(filtered))
     ck(key+':native_success',state=='ok' and int(p)==len(wanted) and int(f)==int(i)==int(m)==0)
     if key in ('default_writer','supervisord'):ck(key+':full_target_filtered_zero',int(filtered)==0)
   if not entry['missing']:
    try:
     command=obj(prefix+'command.json');argv=command['argv'];entry['command']=command
     ck(key+':exact_native_argv',argv[:2]==['bazel','test'] and argv[-1]==target and [v for v in argv if v.startswith('//')]==[target] and [v.split('=',1)[1] for v in argv if v.startswith('--test_arg=')]==expected['case_arguments'][key] and command['expected_tests']==wanted)
     ck(key+':unchanged_budget_attempts',all(v in argv for v in ['--jobs=2','--cache_test_results=no','--flaky_test_attempts=1','--platforms='+configured]) and not any(v.startswith(('--test_timeout=','--runs_per_test=','--test_sharding_strategy=')) for v in argv))
     events=[json.loads(line) for line in read(prefix+'build-events.jsonl').splitlines() if line.strip()]
     attempts=[e for e in events if 'testResult' in e.get('id',{})];summaries=[e for e in events if 'testSummary' in e.get('id',{})];completions=[e for e in events if e.get('id',{}).get('targetCompleted',{}).get('label')==target]
     entry.update(bep_attempts=attempts,bep_summaries=summaries,bep_completions=completions)
     ck(key+':one_native_attempt',len(attempts)==len(summaries)==len(completions)==1)
     if len(attempts)==len(summaries)==len(completions)==1:
      ai=attempts[0]['id']['testResult'];ar=attempts[0]['testResult'];si=summaries[0]['id']['testSummary'];sr=summaries[0]['testSummary'];ci=completions[0]['id']['targetCompleted'];cr=completions[0]['completed']
      ck(key+':attempt_config_binding',ai.get('label')==si.get('label')==target and ai.get('configuration')==si.get('configuration')==ci.get('configuration') and all(ai.get(k)==1 for k in ('run','shard','attempt')))
      ck(key+':single_uncached',all(sr.get(k)==1 for k in ('totalRunCount','runCount','attemptCount')) and sr.get('totalNumCached',0)==0 and ar.get('cachedLocally',False) is False and ar.get('executionInfo',{}).get('cachedRemotely',False) is False)
      ck(key+':BEP_pass',ar.get('status')==sr.get('overallStatus')=='PASSED')
      ck(key+':original_timeout',cr.get('success') is True and int(cr.get('testTimeoutSeconds',-1))==expected['expected_timeouts'][key] and cr.get('testTimeout')==str(expected['expected_timeouts'][key])+'s')
     entry['outer_bazel_exit']=int(read(prefix+'native.exit'));ck(key+':Bazel_zero',entry['outer_bazel_exit']==0)
     elf=obj(prefix+'binary-identities.json');entry['ci_elf_identity_records']=elf
     ck(key+':one_CI_ELF_record',len(elf)==1 and elf[0].get('bytes',0)>0 and re.fullmatch(r'[0-9a-f]{64}',elf[0].get('sha256','')) is not None)
    except Exception as error:ck(key+':native_evidence_parse',False);entry['independent_reader_error']=repr(error)
   entry['status']='PASS' if all(c['ok'] for c in checks[start:]) else 'FAIL_OR_INCOMPLETE'
  def source_receipt(record):return record.get('source_before')==record.get('source_after')=={'commit':selected,'tree':T,'status':''}
  if group=='feature-parity':
   try:
    record=obj('configured_features/result.json');result['configured_features']=record
    prefix='//codex-rs/hepta-agentd:';normal=['default','production-cognitive-write'];qual=['production-cognitive-write','qualification-cognitive-write']
    roots={prefix+l:{'features':f,'source':'codex-rs/hepta-agentd/'+s} for l,f,s in [('hepta-agentd',normal,'src/lib.rs'),('codex-hepta-agentd',normal,'src/main.rs'),('hepta-agentd-cognitive_product_e2e-test',normal,'tests/cognitive_product_e2e.rs'),('hepta-agentd-cognitive-write-qualification-lib',qual,'src/lib.rs'),('hepta-agentd-cognitive-write-qualification-test-bin',qual,'src/lib.rs'),('hepta-agentd-cognitive-product-qualification-bin',qual,'src/main.rs'),('hepta-agentd-cognitive-product-qualification-test-bin',qual,'tests/cognitive_product_e2e.rs')]}
    raw=read('configured_features/aquery.stdout');observed=parser.inspect_actions(json.loads(raw),roots);parser.validate_actions(observed,roots)
    ck('independent_seven_roots',observed==record['actions'] and record['result']=='PASS' and record['analysis_exit']==0 and int(read('configured_features/analysis.exit'))==0)
    ck('configured_source_hash',source_receipt(record) and record['stdout_sha256']==sha(raw) and record['stdout_bytes']==len(raw))
   except Exception as error:ck('configured_metadata_parse',False);result['configured_reader_error']=repr(error)
  else:
   ck('exact_helper_verifier', 'verify-exec-helper.py' in names and read('verify-exec-helper.py').decode()==helper)
   phases={};result['helper_metadata']=phases;triple='x86_64-unknown-linux-'+('musl' if platform=='musl' else 'gnu')
   for phase in ('pre','post'):
    prefix='exec_helper/'+phase+'/'
    if prefix+'result.json' not in names:ck('helper_'+phase+':complete',False);phases[phase]={'result':'MISSING'};continue
    record=obj(prefix+'result.json');phases[phase]=record
    ck('helper_'+phase+':PASS',record.get('result')=='PASS')
    ck('helper_'+phase+':source',source_receipt(record))
    ck('helper_'+phase+':bounded_metadata_only',record.get('tests_executed')==record.get('native_or_helper_invocations')==0 and record.get('phase_limit_seconds')==300 and record.get('work_limit_seconds')==255 and record.get('client_stop_reserve_seconds')==45 and record.get('elapsed_seconds',301)<=300)
    try:ck('helper_'+phase+':formatter',read(prefix+'runfiles.cquery.bzl').decode()==hns['FORMATTER'])
    except Exception as error:ck('helper_'+phase+':formatter',False)
    for key in ('exec_discovery','exec_fs'):
     item=record.get('cases',{}).get(key,{});sub=prefix+key+'/';label,binary,wanted=expected['cases'][key]
     case={'target':label,'source':hns['ROOT_SOURCES'][key],'names':wanted,'arguments':expected['case_arguments'][key]}
     try:
      ck('helper_'+phase+':'+key+':case',item.get('result')=='PASS' and item.get('case')==case and item.get('triple')==triple)
      configured_graph=hns['inspect_graph'](obj(sub+'aquery.stdout'),case,triple,parser) if phase=='pre' else phases['pre']['cases'][key]['configured']
      ck('helper_'+phase+':'+key+':actual_configuration',configured_graph==item['configured'])
      declaration=hns['inspect_cquery'](read(sub+'cquery.stdout'),case,configured_graph,parser);ck('helper_'+phase+':'+key+':actual_runfiles',declaration==item['runfiles'])
      for query in (('aquery','cquery') if phase=='pre' else ('cquery',)):
       qr=obj(sub+query+'-result.json');command=obj(sub+query+'-command.json');argv=command['argv']
       ck('helper_'+phase+':'+key+':'+query+':bounded_success',qr['exit']==0 and qr['deadline_expired'] is False and qr['client_stop_confirmed'] is True and command['phase_seconds']==300 and command['stop_reserve_seconds']==45)
       ck('helper_'+phase+':'+key+':'+query+':scope',argv[:2]==['bazel',query] and '--platforms='+configured in argv and 'deps('+label+')' in argv[-1] and [a.split('=',1)[1] for a in argv if a.startswith('--test_arg=')]==case['arguments'])
       for stream in ('stdout','stderr'):
        data=read(sub+query+'.'+stream);ck('helper_'+phase+':'+key+':'+query+':'+stream+'_hash',qr[stream]['bytes']==len(data) and qr[stream]['sha256']==sha(data))
      if phase=='post':
       ck('helper_post:'+key+':same_runfiles',declaration==phases['pre']['cases'][key]['runfiles'])
       for which in ('helper','test'):
        elf=item[which+'_elf'];allowed=[None,'/lib/ld-musl-x86_64.so.1'] if platform=='musl' else [None,'/lib64/ld-linux-x86-64.so.2','/lib/x86_64-linux-gnu/ld-linux-x86-64.so.2']
        ck('helper_post:'+key+':'+which+'_ELF_record',elf['configured_path']==declaration[which]['path'] and elf['bytes']>64 and re.fullmatch(r'[0-9a-f]{64}',elf['sha256']) is not None and elf['elf_machine']==62 and elf['elf_type'] in (2,3) and elf['pt_interp'] in allowed and elf['configured_target_triple']==triple and elf['executed'] is False)
       ck('helper_post:'+key+':original_parent_ELF',obj(key+'/binary-identities.json')==[{k:item['test_elf'][k] for k in ('path','bytes','sha256')}])
     except Exception as error:ck('helper_'+phase+':'+key+':independent_parse',False);result.setdefault('helper_reader_errors',[]).append({'phase':phase,'case':key,'error':repr(error)})
 result['reported_native_passed']=sum(x.get('passed',0) for x in result['cases'].values());result['reported_native_failed']=sum(x.get('failed',0) for x in result['cases'].values())
 result['all_checks_pass']=all(c['ok'] for c in checks);result['workflow_job_success']=job.get('conclusion')=='success'
 result['lane_qualified']=result['all_checks_pass'] and result['workflow_job_success'];result['native_expected_count']=sum(len(v['expected_names']) for v in result['cases'].values())
 return result

def main():
 global ROOT
 assert len(sys.argv)==4, "usage: external_reader.py DATA_ROOT PINNED_MANIFEST NEW_OUTPUT"
 ROOT=Path(sys.argv[1]).resolve(strict=True);manifest_path=Path(sys.argv[2]);output=Path(sys.argv[3])
 assert not output.exists(), "preserve any existing receipt"
 raw=manifest_path.read_bytes()
 assert len(raw)==7541 and sha(raw)=="0d3786126c78286bc2cc961137337196f728aff04efd644e55f2ffcef1138c10"
 manifest=json.loads(raw)
 assert manifest["run_id"]==41746794500 and manifest["actual_native_passed"]==132 and manifest["actual_native_failed"]==0 and manifest["exec_native_not_executed"]==8
 for item in manifest["files"]:
  name=PurePosixPath(item["path"]);assert not name.is_absolute() and ".." not in name.parts
  b=(ROOT/str(name)).read_bytes();assert len(b)==item["bytes"] and sha(b)==item["sha256"],str(name)
 lanes=[
 (13284682700,"head","gnu","feature-parity"),(13284987969,"head","musl","feature-parity"),
 (13285141555,"prospective-merge","gnu","feature-parity"),(13284448668,"prospective-merge","musl","feature-parity"),
 (13285571889,"head","gnu","remaining29"),(13284219204,"head","musl","remaining29"),
 (13284998019,"prospective-merge","gnu","remaining29"),(13284549137,"prospective-merge","musl","remaining29")]
 rows=[]
 for aid,kind,platform,group in lanes:
  folder=ROOT/str(aid);metadata=json.loads((folder/"official-artifact.json").read_text());job=json.loads((folder/"terminal-job.json").read_text())
  assert metadata["id"]==aid
  r=audit(folder/"original.zip",metadata,job,kind,platform,group)
  expected=6 if group=="feature-parity" else 27
  assert r["reported_native_passed"]==expected and r["reported_native_failed"]==0
  for key,item in r["cases"].items():
   if key not in ("exec_discovery","exec_fs"):assert item["status"]=="PASS", (aid,key)
   else:assert item["missing"] and item.get("passed",0)==0 and item.get("failed",0)==0
  if group=="feature-parity":assert r["lane_qualified"] and job["conclusion"]=="success"
  else:assert not r["lane_qualified"] and job["conclusion"]=="failure"
  rows.append({"artifact_id":aid,"kind":kind,"platform":platform,"group":group,"official_size":r["zip_bytes"],"official_sha256":r["zip_sha256"],"workflow_conclusion":job["conclusion"],"native_passed":r["reported_native_passed"],"native_failed":r["reported_native_failed"],"not_executed":0 if group=="feature-parity" else 2,"cases":{k:{x:v[x] for x in ("status","expected_names","observed_names","running_counts","native_summaries","passed","failed","ignored","filtered","missing") if x in v} for k,v in r["cases"].items()},"failed_checks":[c["name"] for c in r["checks"] if not c["ok"]]})
 result={"schema":"hepta-normal140-portable-offline-v1","timestamp":datetime.datetime.now(datetime.timezone.utc).isoformat(),"source":{"head":H,"merge":M,"tree":T,"harness":S},"manifest_sha256":sha(raw),"author_reader_sha256":sha(Path(__file__).read_bytes()),"lanes":rows,"native_passed":sum(r["native_passed"] for r in rows),"native_failed":sum(r["native_failed"] for r in rows),"exec_not_executed":sum(r["not_executed"] for r in rows),"new_native_executions":0,"artifact_code_executions":0,"network_calls":0,"outcome":"VERIFIED_ORIGINAL_132_PASS_8_UNEXECUTED_WITH_FOUR_WORKFLOW_FAILURES"}
 assert result["native_passed"]==132 and result["native_failed"]==0 and result["exec_not_executed"]==8
 write(output,result)
 print(json.dumps({"path":str(output),"bytes":output.stat().st_size,"sha256":sha(output.read_bytes()),"outcome":result["outcome"],"counts":[result["native_passed"],result["native_failed"],result["exec_not_executed"]]},indent=2))
if __name__=="__main__":main()
