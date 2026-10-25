"""Derive the six reviewed Windows owner dependency edges; never publish raw streams."""
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tomllib
import math
import time
import urllib.request
import windows_owner_lock_support as support
import windows_owner_lock_diagnostics as diagnostics

BRANCH = 'research/dot-windows-owner-lock-generation-7896-20261025'
BASE_TREE = '215a696ea5fe0c7f87aae7fd4da283883b28027c'
BASE = '7896d07a8de6a05cd94e9cbbcc6435be8800bc21'
LOCKS = ('codex-rs/Cargo.lock', 'MODULE.bazel.lock')
BLOBS = {'.bazelversion': 'f7ee06693c17a06e2a0f51ef7eb2a61866e77b8e', '.bazelrc': '0ce81ff3d71d30aeedd7240ee001dd8166364ee2', 'codex-rs/deny.toml': '677f941360b2d82ab96aa4d419d97f4616cc2194', 'MODULE.bazel': 'a49ef6c1cf4cf6b12f76296cd488c93f0753905b', 'tools/argument-comment-lint/Cargo.lock': '1795ff683b86672de2bd2a48a41b4274e3f63d2a', 'justfile': 'a215a76cf407ace9715bca39c20497014e7dd4dc', 'codex-rs/Cargo.lock': '62b728f0bf795100627d72cb9af433faf3c24c0a', 'codex-rs/Cargo.toml': 'd2703b590935ab17316e6c258657c0ce5ab7412a', 'MODULE.bazel.lock': '42c81bc19e21627d642c88fa753d530aa27eab4b', 'codex-rs/utils/path-utils/src/lib.rs': 'e09042ba01233b924b862ee08121d3473faa0b91', 'codex-rs/hepta-agentd/src/prompt_runtime.rs': 'a4a755a5adc6005cd917b3e8ccc3995d6d34fd67', 'codex-rs/hepta-agentd/src/prompt_runtime_tests.rs': '32b9ecb144e075cce5f48f2490fb629dcf6d7e7d', 'codex-rs/hepta-contracts/src/authority_lease.rs': 'd59bb4bf8582502c085253d87c6f81f59823c027', 'codex-rs/hepta-contracts/src/final_use_store.rs': '3e5b562ce2ccb12cfff3023e16530c03ec0e8836', 'codex-rs/hepta-prompt-registry/src/durable.rs': '3664b6c697a2af1f38befe00d899d3ed4754e5ee', 'codex-rs/hepta-agentd/Cargo.toml': '5d13cd8f355bab3ecb95f8c068517de200dd143f', 'codex-rs/hepta-contracts/Cargo.toml': 'cab373fecdfb7eba529753ecbb4943bc46ceec32', 'codex-rs/hepta-prompt-registry/Cargo.toml': '61676abe534702cd1c665197212065ec2d267f3f', 'codex-rs/utils/path-utils/Cargo.toml': 'd1503fd060c960845b2f514cbe69f824291eff07'}
OVERLAY_INPUT = Path(__file__).with_name("windows_owner_overlay.json")
OVERLAY_BLOB = '9b4c0c67d968e0b4f6d7a054ee8649390289e125'
CRATE_FACTS = '@@rules_rs+//rs:extensions.bzl%crate'
REGISTRY = 'registry+https://github.com/rust-lang/crates.io-index'



class GateError(ValueError):
    def __init__(self, code):
        self.code = code
        super().__init__(code)


def require(condition, reason):
    if not condition:
        raise GateError(reason)


def error_code(error):
    return error.code if isinstance(error, GateError) else 'unexpected_exception'


def digest(data):
    return hashlib.sha256(data).hexdigest()


def blob(data):
    return hashlib.sha1(b'blob ' + str(len(data)).encode() + b'\0' + data).hexdigest()


def read_lock(path):
    require(path.is_file() and not path.is_symlink(), 'lock_missing_or_symlink')
    require(path.stat().st_size <= 8 * 1024**2, 'lock_size_limit')
    return path.read_bytes()


def typed_equal(a, b):
    if type(a) is not type(b):
        return False
    if isinstance(a, dict):
        return a.keys() == b.keys() and all(typed_equal(a[k], b[k]) for k in a)
    if isinstance(a, list):
        return len(a) == len(b) and all(typed_equal(x, y) for x, y in zip(a, b))
    return a == b


def package_key(package):
    return package['name'], package['version'], package.get('source')


def strict_json(data):
    def pairs(items):
        result = {}
        for key, value in items:
            require(key not in result, 'duplicate_json_key')
            result[key] = value
        return result
    def invalid_constant(value):
        raise GateError('nonfinite_json_number')
    def finite(value):
        result=float(value);require(math.isfinite(result),'nonfinite_json_number');return result
    return json.loads(data, object_pairs_hook=pairs, parse_constant=invalid_constant,parse_float=finite)


def cargo_lexical_gate(original, updated):
    """No opaque TOML comments/trivia may add content outside parsed closure.
    Restrict to Cargo-generated single-line basic strings and ASCII syntax.
    Parser below independently validates the complete values and structure.
    """
    known_comments = {line.strip() for line in original.decode().splitlines()
                      if line.strip().startswith('#')}
    for line in updated.decode().splitlines():
        stripped = line.strip(' \t\r')
        if stripped.startswith('#'):
            require(stripped in known_comments, 'unexpected_cargo_comment')
            continue
        # No literal/multiline strings, inline comments, or non-ASCII syntax.
        remainder = re.sub(r'"(?:[^"\\\r\n]|\\.)*"', '""', line)
        require(re.fullmatch(r'[a-zA-Z0-9_=\[\],." \t\r-]*', remainder) is not None,
                'unreviewed_cargo_lexical_content')


def known_lock_content(before, after):
    cargo_lexical_gate(before[LOCKS[0]], after[LOCKS[0]])
    cargo_delta(before[LOCKS[0]], after[LOCKS[0]])
    bazel_delta(before[LOCKS[1]], after[LOCKS[1]])


EDGE_ADDITIONS = {
    'codex-hepta-agentd': ['codex-utils-path'],
    'codex-hepta-contracts': ['codex-utils-path'],
    'codex-hepta-prompt-registry': ['codex-utils-path','pretty_assertions'],
    'codex-utils-path': ['winapi-util','windows-sys 0.52.0'],
}
REQUIRED_TARGETS = [('codex-utils-path','0.0.0',None),('pretty_assertions','1.4.1',REGISTRY),
                    ('winapi-util','0.1.11',REGISTRY),('windows-sys','0.52.0',REGISTRY)]

def cargo_delta(original, updated):
    """Exactly six existing-package dependency edges; no package upgrade or acquisition policy change."""
    a,b=tomllib.loads(original.decode()),tomllib.loads(updated.decode())
    require(typed_equal({k:v for k,v in a.items() if k!='package'},{k:v for k,v in b.items() if k!='package'}),'cargo_nonpackage_drift')
    old={package_key(x):x for x in a['package']};new={package_key(x):x for x in b['package']}
    require(len(old)==len(a['package']) and len(new)==len(b['package']),'duplicate_packages')
    require(old.keys()==new.keys(),'unexpected_package_added_removed_or_version')
    require(all(k in old for k in REQUIRED_TARGETS),'required_baseline_package_missing')
    for name in EDGE_ADDITIONS:
        require(len([k for k in old if k[0]==name and k[2] is None])==1,'workspace_package_ambiguous')
    # Every short edge must resolve to exactly one existing package; the one
    # duplicated name is explicitly versioned and must resolve uniquely too.
    for additions in EDGE_ADDITIONS.values():
        for edge in additions:
            parts=edge.split(' ');matches=[k for k in old if k[0]==parts[0] and (len(parts)==1 or k[1]==parts[1])]
            require(len(matches)==1,'edge_resolution_ambiguous')
    for key,package in old.items():
        expected=copy.deepcopy(package)
        if key[2] is None and key[0] in EDGE_ADDITIONS:
            deps=expected.get('dependencies',[]);extra=EDGE_ADDITIONS[key[0]]
            require(isinstance(deps,list) and all(isinstance(x,str) for x in deps),'invalid_workspace_edges')
            require(not any(x in deps for x in extra),'baseline_already_has_edge')
            expected['dependencies']=sorted(deps+extra)
        require(typed_equal(expected,new[key]),'unexpected_package_record_or_edge')
    return {'added_edges':EDGE_ADDITIONS,'edge_count':6,'versions_checksums_sources_unchanged':True}


def bazel_delta(original, updated):
    """No package versions changed: initially accept no semantic Bazel delta."""
    a, b = strict_json(original), strict_json(updated)
    for document in (a, b):
        facts = document.get('facts', {}).get(CRATE_FACTS)
        require(isinstance(facts, dict), 'bazel_schema_not_reviewed')
        for value in facts.values():
            require(isinstance(value, str), 'bazel_fact_not_string')
            strict_json(value)  # Reject duplicate/opaque embedded JSON even if byte-equal.
    require(typed_equal(a, b), 'unexpected_bazel_registry_extension_or_fact_drift')


def overlay_items():
    data=read_lock(OVERLAY_INPUT)
    require(blob(data)==OVERLAY_BLOB,'overlay_payload_mismatch')
    parsed=strict_json(data)
    require(set(parsed)=={'schema','base','base_tree','files'} and parsed['schema']==1 and parsed['base']==BASE and parsed['base_tree']==BASE_TREE,'overlay_schema')
    items=parsed['files'];require(isinstance(items,list) and len(items)==22,'overlay_roster')
    paths=[]
    for item in items:
        require(set(item)=={'path','before_blob','after_blob','sha256','content'},'overlay_item_schema')
        name=item['path'];require(isinstance(name,str) and name.startswith('codex-rs/') and all(x not in {'','.','..'} for x in name.split('/')),'overlay_path')
        require('network-proxy' not in name and name not in LOCKS,'overlay_excluded_scope')
        data=item['content'].encode();require(blob(data)==item['after_blob'] and digest(data)==item['sha256'],'overlay_content')
        paths.append(name)
    require(len(set(paths))==22,'overlay_duplicate_path')
    return items

def overlay_gate(repo, applied=False):
    for item in overlay_items():
        path=repo/item['path']
        require(not path.is_symlink() and all(not p.is_symlink() for p in path.parents if p!=repo.parent),'overlay_symlink')
        if applied:require(blob(read_lock(path))==item['after_blob'],'overlay_after_mismatch')
        elif item['before_blob'] is None:require(not path.exists(),'overlay_new_path_exists')
        else:require(blob(read_lock(path))==item['before_blob'],'overlay_before_mismatch')


def budget_remaining(out):
    path = Path(os.environ['LOCK_GENERATION_BUDGET'])
    require(path.is_file() and not path.is_symlink() and path.stat().st_size < 4096, 'budget_missing')
    raw = path.read_bytes()
    require(digest(raw) == os.environ.get("LOCK_GENERATION_BUDGET_SHA256"), "budget_identity_changed")
    record = strict_json(raw)
    require(set(record) == {'start', 'deadline', 'seconds', 'head', 'platform'}, 'budget_schema')
    require(record['platform'] == 'linux' and sys.platform == 'linux', 'budget_platform')
    require(type(record['seconds']) is int and record['seconds'] == 2700, 'budget_duration')
    require(all(type(record[k]) in (int, float) and math.isfinite(record[k]) for k in ('start', 'deadline')), 'budget_number')
    require(record['deadline'] == record['start'] + 2700, 'budget_construction')
    require(record['head'] == os.environ.get('GITHUB_SHA') and re.fullmatch('[0-9a-f]{40}', record['head']), 'budget_head')
    now = time.monotonic()
    require(record['start'] <= now < record['deadline'], 'shared_budget_expired_or_future')
    return record['deadline'] - now


ACTIVE_BUDGET_OUT=None

def budget_git(repo,env,*args):
    if ACTIVE_BUDGET_OUT is not None:budget_remaining(ACTIVE_BUDGET_OUT)
    result=support.git(repo,env,*args)
    if ACTIVE_BUDGET_OUT is not None:budget_remaining(ACTIVE_BUDGET_OUT)
    return result

def budget_identity(repo,commit,tree,env):
    require(budget_git(repo,env,'rev-parse','HEAD').decode().strip()==commit,'source_commit_mismatch')
    if tree:require(budget_git(repo,env,'rev-parse','HEAD^{tree}').decode().strip()==tree,'source_tree_mismatch')
    require(not budget_git(repo,env,'status','--porcelain','--untracked-files=all'),'source_dirty')

def configuration_gate(repo):
    """Never turn opt-in agreement/remote/security knobs into implicit acceptance."""
    require(not (repo / 'user.bazelrc').exists(), 'user_bazelrc_present')
    rc = (repo / '.bazelrc').read_text()
    for line in rc.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith('#'):
            continue
        if re.search(r'(?i)(EULA|accept.*agreement|credential|api.key|authorization)', stripped):
            raise GateError('bazel_legal_or_credential_configuration')
        # Endpoint-bearing opt-in configurations may exist but are never selected.
        head = stripped.split()[0]
        if ':' not in head:
            require(not re.search(r'--(?:remote_executor|remote_cache|bes_backend|remote_header|config)=', stripped),
                    'implicit_remote_configuration')
    module = (repo / 'MODULE.bazel').read_text()
    active = '\n'.join(line for line in module.splitlines() if not line.lstrip().startswith('#'))
    require('BAZEL_MSVC_RUNTIME_VISUAL_STUDIO_EULA=1' not in active, 'implicit_eula_acceptance')
    require(not re.search(r'use_home_cargo_credentials\s*=\s*True', active), 'home_credentials_enabled')
    triples = re.findall(r'platform_triples\s*=\s*\[(.*?)\]', active, re.S)
    require(len(triples) == 2 and all(len(re.findall(r'"[a-z0-9_-]+"', x)) == 10 for x in triples),
            'platform_roster_changed')


CONTROL_FILES = (
    '.github/workflows/windows-owner-lock-generation.yml',
    '.github/scripts/windows_owner_lock_generator.py',
    '.github/scripts/windows_owner_lock_support.py',
    '.github/scripts/windows_owner_lock_diagnostics.py',
    '.github/scripts/windows_owner_overlay.json',
    '.github/scripts/test_windows_owner_lock_generator.py',
)


def control_gate(control, env, before=None):
    sha, workflow_sha = os.environ.get('GITHUB_SHA', ''), os.environ.get('GITHUB_WORKFLOW_SHA', '')
    require(bool(re.fullmatch('[0-9a-f]{40}', sha)) and sha == workflow_sha, 'control_event_workflow_sha_mismatch')
    require(os.environ.get('GITHUB_EVENT_NAME') == 'push'
            and os.environ.get('GITHUB_REF') == 'refs/heads/' + BRANCH,
            'control_trigger_mismatch')
    require(os.environ.get('GITHUB_WORKFLOW_REF') ==
            'TrillionniumFoundation/hepta-private-ci/.github/workflows/windows-owner-lock-generation.yml@refs/heads/' + BRANCH,
            'control_workflow_ref_mismatch')
    budget_identity(control, sha, None, env)
    tree = budget_git(control, env, 'rev-parse', 'HEAD^{tree}').decode().strip()
    require(bool(re.fullmatch('[0-9a-f]{40}', tree)), 'control_tree_invalid')
    receipt = {'event_sha': sha, 'workflow_sha': workflow_sha, 'tree': tree, 'branch': BRANCH, 'event': 'push', 'files': {}}
    for path in CONTROL_FILES:
        expected = budget_git(control, env, 'rev-parse', 'HEAD:' + path).decode().strip()
        data = read_lock(control / path)
        require(blob(data) == expected, 'control_file_blob_mismatch')
        receipt['files'][path] = {'git_blob': expected, 'sha256': digest(data)}
    require(before is None or receipt == before, 'control_changed')
    return receipt


def checkout_gate(repo,control,env):
    # Bound separate checkouts, no cross-history diff or additional fetch.
    require(budget_git(control,env,'rev-parse','HEAD^').decode().strip()==BASE,'control_parent_mismatch')
    maps=[]
    for root in (repo,control):
        rows=budget_git(root,env,'ls-files','--stage','-z');mapping={}
        require(bool(rows) and rows.endswith(b'\0'),'tracked_map_framing')
        for row in rows[:-1].split(b'\0'):
            meta,name=row.split(b'\t',1);parts=meta.split(b' ')
            require(len(parts)==3 and parts[2]==b'0' and parts[0] in {b'100644',b'100755',b'120000'} and re.fullmatch(b'[0-9a-f]{40}',parts[1]),'tracked_map_entry')
            require(name not in mapping,'tracked_map_duplicate');mapping[name]=(parts[0],parts[1])
        maps.append(mapping)
    source,controls=maps;allowed={x.encode() for x in CONTROL_FILES}
    require(set(controls)-set(source)==allowed and not set(source)-set(controls),'control_path_roster')
    require(all(source[k]==controls[k] for k in source),'control_source_drift')
    for name in CONTROL_FILES:require(controls[name.encode()]==(b'100644',blob(read_lock(control/name)).encode()),'control_map_blob')
    return {'source_entries':len(source),'control_entries':len(controls),'only_added_control_paths':list(CONTROL_FILES)}

def publication_allowed(report):
    return (report.get('qualified') is True and report.get('source_after_confirmed') is True
            and report.get('known_lock_content_confirmed') is True
            and report.get('control_after') == report.get('control_before')
            and report.get('control_before') is not None
            and all(command.get('cleanup', {}).get('confirmed') is True
                    and command.get('stop') is None
                    and command.get('exit') == 0
                    for command in report['commands']))


def diagnostic_allowed(report):
    # Localization is useful only for successful, fully quiescent generation
    # whose known-content verdict held. It cannot authorize lock publication.
    return (report.get('qualified') is False
            and report.get('source_after_confirmed') is True
            and report.get('control_before') is not None
            and report.get('control_after') == report.get('control_before')
            and bool(report.get('commands'))
            and all(command.get('cleanup', {}).get('confirmed') is True
                    and command.get('stop') is None and command.get('exit') == 0
                    for command in report['commands']))


def retain_hold_diagnostic(report, repo, before, after, confirm_final):
    if not diagnostic_allowed(report) or support.OWNERSHIP_UNCERTAIN:
        return
    path = LOCKS[1]
    if set(before) != set(LOCKS) or set(after) != set(LOCKS) or before[path] == after[path]:
        return
    try:
        require(blob(before[path]) == BLOBS[path], 'diagnostic_baseline_unbound')
        for retained_path, data in after.items():
            require(read_lock(repo / retained_path) == data, 'diagnostic_snapshot_changed')
        summary = diagnostics.summarize(before[path], after[path], BLOBS[path])
        confirm_final()  # Recheck source/control after bounded localization.
        require(not support.OWNERSHIP_UNCERTAIN, 'diagnostic_cleanup_uncertain')
        for retained_path, data in after.items():
            require(read_lock(repo / retained_path) == data, 'diagnostic_snapshot_changed')
        report['bazel_hold_summary'] = summary
    except Exception:
        # Never stringify arbitrary exceptions or retain partial localized paths.
        report['bazel_hold_summary'] = {
            'format_version': 1, 'status': 'unavailable', 'complete': False,
            'reason': 'final_diagnostic_gate_failed'}


def bootstrap_summary(receipt, control, binary):
    require(isinstance(receipt, dict), 'bootstrap_receipt_missing')
    require(receipt.get('source_commit') == BASE and receipt.get('source_tree') == BASE_TREE,
            'bootstrap_source_binding')
    require(receipt.get('control_before') == control == receipt.get('control_after'), 'bootstrap_control_binding')
    require(receipt.get('budget_sha256') == os.environ.get('LOCK_GENERATION_BUDGET_SHA256')
            and bool(re.fullmatch('[0-9a-f]{64}', receipt.get('budget_sha256', ''))), 'bootstrap_budget_binding')
    actual = {'bytes': BAZEL_ASSET_BYTES, 'sha256': BAZEL_ASSET_SHA256, 'version': 'bazel 9.0.0'}
    require(receipt.get('bootstrap_passed') is True and receipt.get('actual') == actual,
            'bootstrap_actual_binding')
    commands = receipt.get('commands')
    require(isinstance(commands, list) and len(commands) == 2
            and all(isinstance(c, dict) and c.get('exit') == 0 and c.get('stop') is None
                    and c.get('cleanup', {}).get('confirmed') is True for c in commands),
            'bootstrap_cleanup_binding')
    require(binary.is_file() and not binary.is_symlink() and binary.stat().st_size == BAZEL_ASSET_BYTES
            and digest(binary.read_bytes()) == BAZEL_ASSET_SHA256, 'bootstrap_binary_binding')
    # Reconstruct known fields only; never republish arbitrary prior receipt bytes.
    return {'phase': 'bootstrap_revalidated_by_main', 'source_commit': BASE, 'source_tree': BASE_TREE,
            'actual': actual, 'bootstrap_passed': True, 'cleanup_confirmed': True,
            'control_bound': True, 'budget_bound': True, 'raw_stream_policy': 'never_publish'}


def main(repo, out, control):
    global ACTIVE_BUDGET_OUT
    ACTIVE_BUDGET_OUT=Path(out).resolve()
    repo, out, control = repo.resolve(), out.resolve(), control.resolve()
    out.mkdir(parents=True, exist_ok=True)
    public = out / 'public'
    public.mkdir(exist_ok=True)
    prior_bootstrap = None
    try:
        receipt_path = public / 'bootstrap.json'
        if receipt_path.is_file() and not receipt_path.is_symlink() and receipt_path.stat().st_size <= 65536:
            prior_bootstrap = strict_json(receipt_path.read_bytes())
    except Exception:
        pass  # Fixed HOLD later, never export parse errors or prior untrusted bytes.
    for retained in public.iterdir():
        if retained.name not in {'before-Cargo.lock', 'before-MODULE.bazel.lock', 'report.json'} and retained.is_file():
            retained.unlink()  # Own output directory: never retain prior-run derived bytes.
    report = {'source_commit': BASE, 'source_tree': BASE_TREE, 'raw_stream_policy': 'never_publish', 'qualified': False, 'publish_allowed': False,
              'historical_cause_claim': False, 'commands': [], 'phases': [],
              'budget_sha256': os.environ.get('LOCK_GENERATION_BUDGET_SHA256'),
              'resource_limits': {'shared_seconds_from_precheckout': 2700, 'command_seconds': 1800, 'preflight_free_GiB': 20,
                                  'floor_GiB': 4, 'soft_total_disk_growth_GiB': 8,
                                  'quota_enforced': False}}
    before = {}
    bootstrap_bytes = None
    overlay_applied = False
    env = {k: os.environ[k] for k in ['PATH', 'RUSTUP_HOME'] if k in os.environ}
    env.update(HOME=str(out / 'home'), CARGO_HOME=str(out / 'cargo'),
               RUSTUP_HOME=os.environ.get('RUSTUP_HOME', str(Path.home() / '.rustup')),
               LANG='C.UTF-8', GIT_CONFIG_NOSYSTEM='1', GIT_CONFIG_GLOBAL='/dev/null',
               GIT_TERMINAL_PROMPT='0', CARGO_NET_GIT_FETCH_WITH_CLI='true',
               ASPECT_TOOLS_TELEMETRY='-all', PYTHONDONTWRITEBYTECODE='1')
    Path(env['HOME']).mkdir(exist_ok=True)
    Path(env['CARGO_HOME']).mkdir(exist_ok=True)
    original_cwd = Path.cwd()

    def run(argv, seconds=1800, cwd=None):
        if cwd:
            os.chdir(cwd)
        remaining = budget_remaining(out)
        result, streams = support.capture(argv, env, min(seconds, remaining), disk=out)
        result['shared_budget_seconds_at_start'] = remaining
        report['commands'].append(result)
        budget_remaining(out)  # Includes owned cleanup elapsed time.
        require(result['exit'] == 0 and result['stop'] is None and result['cleanup']['confirmed'], 'owned_command_failed')
        return streams[0].retained()

    def no_unexpected_mutation():
        items=overlay_items();allowed={x['path'] for x in items}
        changed=budget_git(repo,env,'diff','HEAD','--name-only').decode().splitlines()
        require(set(changed)<=set(LOCKS)|allowed,'source_mutated_outside_overlay_lock_allowlist')
        overlay_gate(repo,overlay_applied)
        expected_new={x['path'] for x in items if x['before_blob'] is None} if overlay_applied else set()
        actual_new=set(budget_git(repo,env,'ls-files','--others','--exclude-standard').decode().splitlines())
        require(actual_new==expected_new,'unexpected_untracked_source')
        require(budget_git(repo,env,'rev-parse','HEAD').decode().strip()==BASE,'source_head_changed')


    try:
        budget_remaining(out)
        require(shutil.disk_usage(out).free >= 20 * 1024**3, 'preflight_disk_below_20GiB')
        support.DISK_INITIAL_FREE = shutil.disk_usage(out).free
        report['control_before'] = control_gate(control, env)
        binary = out / 'job-tools' / 'bazel'
        require(shutil.which('bazel', path=env['PATH']) == str(binary), 'bootstrap_path_binding')
        summary = bootstrap_summary(prior_bootstrap, report['control_before'], binary)
        bootstrap_bytes = (json.dumps(summary, indent=2) + '\n').encode()
        (public / 'bootstrap.json').write_bytes(bootstrap_bytes)
        budget_identity(repo, BASE, None, env)
        require(budget_git(repo, env, 'rev-parse', 'HEAD^{tree}').decode().strip() == BASE_TREE, 'source_tree_mismatch')
        checkout_gate(repo,control,env)
        for path, expected in BLOBS.items():
            require(blob(read_lock(repo / path)) == expected, 'immutable_input_blob_mismatch')
        budget_remaining(out)
        require(support.input_gate(repo, env), 'complete_cargo_input_gate_failed')
        budget_remaining(out)
        configuration_gate(repo)
        before = {path: read_lock(repo / path) for path in LOCKS}
        report['source_before'] = {p: {'sha256': digest(b), 'git_blob': blob(b)} for p,b in before.items()}
        for path, data in before.items():
            (public / ('before-' + Path(path).name)).write_bytes(data)
        for tool in ['cargo', 'rustc', 'bazel']:
            resolved = shutil.which(tool, path=env['PATH'])
            require(resolved is not None, 'required_tool_missing')
            report.setdefault('tool_paths', {})[tool] = {'sha256': digest(Path(resolved).read_bytes())}
        require(run(['cargo', '+1.95.0', '-V'], 60, repo).startswith(b'cargo 1.95.0 '), 'cargo_version_mismatch')
        require(run(['rustc', '+1.95.0', '-Vv'], 60, repo).startswith(b'rustc 1.95.0 '), 'rustc_version_mismatch')
        for tool in ['cargo', 'rustc']:
            actual = Path(run(['rustup', 'which', '--toolchain', '1.95.0', tool], 60, repo).decode().strip())
            require(actual.is_file(), 'toolchain_binary_missing')
            report['tool_paths'][tool + '-actual'] = {'sha256': digest(actual.read_bytes())}
        bazel = ['bazel', '--batch', '--nosystem_rc', '--nohome_rc',
                 '--output_user_root=' + str(out / 'bazel-root'),
                 '--output_base=' + str(out / 'bazel-output'),
                 '--noexperimental_remote_repo_contents_cache']
        require(run(bazel + ['version', '--gnu_format'], 120, repo).strip() == b'bazel 9.0.0', 'bazel_version_mismatch')
        overlay_gate(repo)
        for item in overlay_items():
            path=repo/item['path'];path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(item['content'].encode())
        overlay_applied=True
        overlay_gate(repo,True)
        report['overlay']={'payload_blob':OVERLAY_BLOB,'file_count':22,'excluded_stage':'01-rama-api'}
        run(['cargo', '+1.95.0', 'metadata', '--all-features', '--format-version=1'], cwd=repo / 'codex-rs')
        no_unexpected_mutation()
        require(read_lock(repo / LOCKS[1]) == before[LOCKS[1]], 'bazel_lock_changed_during_cargo')
        report['phases'].append(cargo_delta(before[LOCKS[0]], read_lock(repo / LOCKS[0])))
        cargo_after = read_lock(repo / LOCKS[0])
        bazel_flags = ['--repository_cache=' + str(out / 'bazel-repository'),
                       '--repo_contents_cache=' + str(out / 'bazel-contents'), '--disk_cache=']
        # Exact just bazel-lock-update recipe, with only isolated storage/startup flags.
        run(bazel + ['mod', 'deps', '--lockfile_mode=update'] + bazel_flags, cwd=repo)
        no_unexpected_mutation()
        require(read_lock(repo / LOCKS[0]) == cargo_after, 'bazel_mutated_cargo_lock')
        bazel_delta(before[LOCKS[1]], read_lock(repo / LOCKS[1]))
        final_hashes = {path: digest(read_lock(repo / path)) for path in LOCKS}
        run(bazel + ['mod', 'deps', '--lockfile_mode=error'] + bazel_flags, cwd=repo)
        # Full metadata may acquire public dependencies; it does not compile them.
        # Bazel validates full cross-platform graph against all ten unchanged triples.
        run(['cargo', '+1.95.0', 'metadata', '--locked', '--offline', '--all-features', '--format-version=1'],
            cwd=repo / 'codex-rs')
        no_unexpected_mutation()
        require(final_hashes == {path: digest(read_lock(repo / path)) for path in LOCKS}, 'qualification_lock_drift')
        report['qualified'] = True
        report['qualification_scope'] = 'six Windows owner edges, unchanged package roster and ten-triple Bazel resolution; no build/runtime/security-clear claim'
    except (ValueError, OSError, KeyError, TypeError, json.JSONDecodeError) as error:
        report['hold'] = error_code(error)
    finally:
        os.chdir(original_cwd)
        # Retain bounded records privately until all commands are quiescent and
        # both independent checkouts have passed their final provenance gates.
        try:
            budget_remaining(out)
            require(not support.OWNERSHIP_UNCERTAIN, 'cleanup_unconfirmed')
            no_unexpected_mutation()
            report['source_after_confirmed'] = True
            report['control_after'] = control_gate(control, env, report.get('control_before'))
            budget_remaining(out)
        except Exception as error:
            report['qualified'] = False
            report['final_gate_hold'] = error_code(error)
        after = {}
        for path in LOCKS:
            try:
                data = read_lock(repo / path)
                after[path] = data
                report.setdefault('source_after', {})[path] = {'sha256': digest(data), 'git_blob': blob(data)}
            except Exception:
                report.setdefault('unavailable_files', []).append(path)
        diff = b''
        if report.get('qualified'):
            try:
                budget_remaining(out)
                require(final_hashes == {path: digest(after[path]) for path in LOCKS}, 'final_snapshot_lock_drift')
                known_lock_content(before, after)
                report['known_lock_content_confirmed'] = True
                import difflib
                diff = ''.join(''.join(difflib.unified_diff(before[path].decode().splitlines(True),
                    after[path].decode().splitlines(True), fromfile='before/'+path, tofile='after/'+path))
                    for path in LOCKS).encode()
                report['diff_sha256'] = digest(diff)
                budget_remaining(out)
                # Exact known-input content closure replaces raw-output screening.
                # No command output participates in the emitted lock bytes or diff.
            except Exception as error:
                report['qualified'] = False
                report['final_gate_hold'] = error_code(error)
        try:
            budget_remaining(out)
            require(bootstrap_bytes is not None, 'bootstrap_unavailable')
            bootstrap_summary(prior_bootstrap, report.get('control_after'), out / 'job-tools' / 'bazel')
            receipt_path = public / 'bootstrap.json'
            require(not receipt_path.is_symlink() and receipt_path.is_file()
                    and receipt_path.read_bytes() == bootstrap_bytes, 'bootstrap_final_receipt_drift')
            budget_remaining(out)
        except Exception as error:
            report['qualified'] = False
            report['bootstrap_final_hold'] = error_code(error)
            receipt_path = public / 'bootstrap.json'
            if receipt_path.is_file() or receipt_path.is_symlink():
                receipt_path.unlink()
            receipt_path.write_text('{"phase":"bootstrap_unavailable","qualified":false}\n')
        try:
            budget_remaining(out)
            allowed=publication_allowed(report)
        except Exception as error:
            allowed=False;report['qualified']=False;report['final_gate_hold']=error_code(error)
        report['publication_gate_passed']=False
        if allowed:
            try:
                # Derived bytes stay OUTSIDE the always-upload public directory.
                # Workflow admits this fixed directory only after main returns0.
                qualified_dir=out/'qualified';qualified_dir.mkdir(mode=0o700)
                payloads={('after-'+Path(path).name):data for path,data in after.items()}
                payloads['locks.diff']=diff
                for name,data in payloads.items():
                    budget_remaining(out);(qualified_dir/name).write_bytes(data);budget_remaining(out)
                require(set(x.name for x in qualified_dir.iterdir())==set(payloads),'private_derived_roster')
                for name,data in payloads.items():
                    path=qualified_dir/name
                    require(path.is_file() and not path.is_symlink() and path.read_bytes()==data,'private_derived_drift')
                    budget_remaining(out)
                report['reviewed_overlay_blob']=OVERLAY_BLOB
                report['publication_gate_passed']=True
            except Exception as error:
                allowed=False;report['qualified']=False;report['final_gate_hold']=error_code(error)
        if not allowed:
            report['qualified']=False;report['publication_gate_passed']=False
            report['withheld']='all_raw_diff_generated_locks'
            for key in ('tool_paths','phases','current_registry_records'):report.pop(key,None)
            def confirm_diagnostic_final():
                budget_remaining(out);no_unexpected_mutation()
                control_gate(control,env,report.get('control_before'));budget_remaining(out)
            try:
                budget_remaining(out)
                retain_hold_diagnostic(report,repo,before,after,confirm_diagnostic_final)
                budget_remaining(out)
            except Exception as error:
                report['final_gate_hold']=error_code(error);report.pop('bazel_hold_summary',None)
        try:
            if report.get('qualified'):budget_remaining(out)
            (public/'report.json').write_text(json.dumps(report,indent=2)+'\n')
            if report.get('qualified'):budget_remaining(out)
        except Exception as error:
            report['qualified']=False;report['publication_gate_passed']=False
            report['withheld']='all_raw_diff_generated_locks';report['final_gate_hold']=error_code(error)
            # Fixed safe HOLD metadata uses outer upload reserve, not new work.
            (public/'report.json').write_text(json.dumps(report,indent=2)+'\n')
    ACTIVE_BUDGET_OUT=None
    return 0 if report['qualified'] else 1



def preflight(repo, out, control):
    global ACTIVE_BUDGET_OUT
    ACTIVE_BUDGET_OUT=Path(out).resolve()
    repo, out, control = repo.resolve(), out.resolve(), control.resolve()
    public = out / 'public'
    public.mkdir(parents=True, exist_ok=True)
    env = {'PATH': os.environ['PATH'], 'HOME': str(out / 'home'),
           'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': '/dev/null', 'GIT_TERMINAL_PROMPT': '0'}
    Path(env['HOME']).mkdir(exist_ok=True)
    result = {'source_commit': BASE, 'source_tree': BASE_TREE, 'raw_stream_policy': 'never_publish', 'qualified': False, 'publish_allowed': False,
              'phase': 'preflight_only', 'historical_cause_claim': False}
    try:
        budget_remaining(out)
        require(shutil.disk_usage(out).free >= 20 * 1024**3, 'preflight_disk_below_20GiB')
        result['control_before'] = control_gate(control, env)
        budget_identity(repo, BASE, None, env)
        require(budget_git(repo, env, 'rev-parse', 'HEAD^{tree}').decode().strip() == BASE_TREE, 'source_tree_mismatch')
        checkout_gate(repo,control,env)
        for path, expected in BLOBS.items():
            require(blob(read_lock(repo / path)) == expected, 'immutable_input_blob_mismatch')
        budget_remaining(out)
        require(support.input_gate(repo, env), 'complete_cargo_input_gate_failed')
        budget_remaining(out)
        configuration_gate(repo)
        overlay_gate(repo)
        for path in LOCKS:
            data = read_lock(repo / path)
            (public / ('before-' + Path(path).name)).write_bytes(data)
            result.setdefault('source_before', {})[path] = {'sha256': digest(data), 'git_blob': blob(data)}
        result['control_after'] = control_gate(control, env, result['control_before'])
        budget_remaining(out)
        result['preflight_passed'] = True
    except (ValueError, OSError, KeyError) as error:
        result['hold'] = error_code(error)
    (public / 'report.json').write_text(json.dumps(result, indent=2) + '\n')
    try:
        if result.get('preflight_passed'):budget_remaining(out)
    except Exception as error:
        result['preflight_passed']=False;result['hold']=error_code(error)
        (public/'report.json').write_text(json.dumps(result,indent=2)+'\n')
    ACTIVE_BUDGET_OUT=None
    return 0 if result.get('preflight_passed') else 1


BAZEL_ASSET_URL = 'https://github.com/bazelbuild/bazel/releases/download/9.0.0/bazel-9.0.0-linux-x86_64'
BAZEL_ASSET_BYTES = 65821854
BAZEL_ASSET_SHA256 = 'c44a93f25398c68f904fa1d19b61d321de6c0d2f09dca375d7bc0dc9b9428403'


class OfficialAssetRedirect(urllib.request.HTTPRedirectHandler):
    def __init__(self):
        self.followed = False

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        from urllib.parse import urlsplit
        target = urlsplit(newurl)
        require(not self.followed and req.full_url == BAZEL_ASSET_URL
                and code in (301, 302, 303, 307, 308)
                and target.scheme == 'https'
                and target.netloc == 'release-assets.githubusercontent.com'
                and target.path.startswith('/github-production-release-asset/20773773/')
                and not target.fragment and not target.username and not target.password,
                'asset_redirect_not_authorized')
        self.followed = True
        # Signed redirect query remains private; never save URL or exception text.
        return urllib.request.Request(newurl, headers={'Accept-Encoding': 'identity'})


def copy_official_asset(response, destination, clock):
    deadline = clock() + 150
    require(response.status == 200, 'asset_http_status')
    require(response.headers.get('Content-Encoding', 'identity') == 'identity', 'asset_encoding')
    require(response.headers.get('Content-Length') == str(BAZEL_ASSET_BYTES), 'asset_size_header')
    total = 0
    hasher = hashlib.sha256()
    with destination.open('xb') as output:
        while True:
            require(clock() < deadline, 'asset_download_deadline')
            chunk = response.read1(min(65536, BAZEL_ASSET_BYTES - total + 1))
            if not chunk:
                break
            total += len(chunk)
            require(total <= BAZEL_ASSET_BYTES, 'asset_byte_cap')
            hasher.update(chunk)
            output.write(chunk)
    require(total == BAZEL_ASSET_BYTES, 'asset_short_body')
    require(hasher.hexdigest() == BAZEL_ASSET_SHA256, 'asset_digest_mismatch')


def download_official_asset(destination):
    """Single unauthenticated public asset request; no retries or fallback."""
    import time
    import urllib.error
    try:
        opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), OfficialAssetRedirect())
        request = urllib.request.Request(BAZEL_ASSET_URL, headers={'Accept-Encoding': 'identity'})
        # Default HTTPSHandler verifies certificates and hostnames. No custom CA,
        # credentials, cookie handler, proxy, netrc, or authorization header.
        with opener.open(request, timeout=20) as response:
            copy_official_asset(response, destination, time.monotonic)
        return 0
    except urllib.error.HTTPError as error:
        return 23 if error.code in (401, 403) else 24
    except Exception:
        return 25


def bootstrap_bazel(repo, out, control):
    global ACTIVE_BUDGET_OUT
    ACTIVE_BUDGET_OUT=Path(out).resolve()
    """Bootstrap only: immutable official binary under the same owned supervisor."""
    repo, out, control = repo.resolve(), out.resolve(), control.resolve()
    public = out / 'public'
    public.mkdir(parents=True, exist_ok=True)
    receipt = {'phase': 'keyless_bazel_bootstrap', 'qualified': False,
               'source_commit': BASE, 'source_tree': BASE_TREE,
               'budget_sha256': os.environ.get('LOCK_GENERATION_BUDGET_SHA256'),
               'raw_stream_policy': 'never_publish', 'asset_url': BAZEL_ASSET_URL,
               'expected_bytes': BAZEL_ASSET_BYTES, 'expected_sha256': BAZEL_ASSET_SHA256,
               'commands': [], 'bootstrap_passed': False}
    tools_dir = out / 'job-tools'
    env = {'PATH': os.environ['PATH'], 'HOME': str(out / 'home'),
           'LANG': 'C.UTF-8', 'GIT_CONFIG_NOSYSTEM': '1', 'GIT_CONFIG_GLOBAL': '/dev/null',
           'GIT_TERMINAL_PROMPT': '0', 'PYTHONDONTWRITEBYTECODE': '1'}
    old_cwd = Path.cwd()
    binary = tools_dir / 'bazel'
    try:
        budget_remaining(out)
        require(shutil.disk_usage(out).free >= 20 * 1024**3, 'preflight_disk_below_20GiB')
        support.DISK_INITIAL_FREE = shutil.disk_usage(out).free
        receipt['control_before'] = control_gate(control, env)
        budget_identity(repo, BASE, BASE_TREE, env)
        require((repo / '.bazelversion').read_bytes() == b'9.0.0\n', 'bazel_version_file_mismatch')
        require(sys.platform == 'linux' and os.uname().machine == 'x86_64', 'bootstrap_platform_mismatch')
        tools_dir.mkdir(mode=0o700)  # Existing directory: HOLD, never overwrite or retry.
        os.chdir(tools_dir)
        command = [sys.executable, str(control / '.github/scripts/windows_owner_lock_generator.py'),
                   '--download-bazel-asset', str(binary)]
        result, streams = support.capture(command, env, min(180, budget_remaining(out)), disk=out)
        receipt['commands'].append(result)
        budget_remaining(out)
        require(result['cleanup']['confirmed'] and result['stop'] is None, 'asset_owned_cleanup_or_timeout')
        require(result['exit'] not in (23, 24), 'public_asset_http_denied_or_failed')
        require(result['exit'] == 0, 'public_asset_download_or_integrity_failed')
        require(binary.is_file() and not binary.is_symlink()
                and binary.stat().st_size == BAZEL_ASSET_BYTES, 'asset_size_mismatch')
        require(digest(binary.read_bytes()) == BAZEL_ASSET_SHA256, 'asset_digest_mismatch')
        binary.chmod(0o700)
        command = [str(binary), '--batch', '--nosystem_rc', '--nohome_rc',
                   '--output_user_root=' + str(out / 'bazel-root'),
                   '--output_base=' + str(out / 'bazel-output'),
                   '--noexperimental_remote_repo_contents_cache', 'version', '--gnu_format']
        result, streams = support.capture(command, env, min(60, budget_remaining(out)), disk=out)
        receipt['commands'].append(result)
        budget_remaining(out)
        require(result['exit'] == 0 and result['stop'] is None and result['cleanup']['confirmed'],
                'bootstrap_version_command_failed')
        require(streams[0].count <= 128 and streams[0].retained().strip() == b'bazel 9.0.0',
                'bootstrap_bazel_version_mismatch')
        require(digest(binary.read_bytes()) == BAZEL_ASSET_SHA256, 'bootstrap_binary_drift')
        receipt['actual'] = {'bytes': binary.stat().st_size, 'sha256': BAZEL_ASSET_SHA256,
                             'version': 'bazel 9.0.0'}
        budget_identity(repo, BASE, BASE_TREE, env)
        receipt['control_after'] = control_gate(control, env, receipt['control_before'])
        require(not support.OWNERSHIP_UNCERTAIN, 'cleanup_unconfirmed')
        budget_remaining(out)
        receipt['bootstrap_passed'] = True
    except Exception as error:
        receipt['hold'] = error_code(error)
    finally:
        os.chdir(old_cwd)
        # Raw streams, redirect URLs, exception strings and partial binary never
        # enter upload directory. No retry or fallback after any failure.
        (public / 'bootstrap.json').write_text(json.dumps(receipt, indent=2) + '\n')
        try:
            if receipt['bootstrap_passed']:budget_remaining(out)
        except Exception as error:
            receipt['bootstrap_passed']=False;receipt['hold']=error_code(error)
            (public/'bootstrap.json').write_text(json.dumps(receipt,indent=2)+'\n')
    ACTIVE_BUDGET_OUT=None
    return 0 if receipt['bootstrap_passed'] else 1


if __name__ == '__main__':
    if sys.argv[1] == '--download-bazel-asset':
        raise SystemExit(download_official_asset(Path(sys.argv[2])))
    if sys.argv[1] == '--bootstrap-bazel':
        raise SystemExit(bootstrap_bazel(Path(sys.argv[2]), Path(sys.argv[3]), Path(sys.argv[4])))
    if sys.argv[1] == '--preflight':
        raise SystemExit(preflight(Path(sys.argv[2]), Path(sys.argv[3]), Path(sys.argv[4])))
    raise SystemExit(main(Path(sys.argv[1]), Path(sys.argv[2]), Path(sys.argv[3])))
