"""Render a separate report only from frozen originals and explicit RESULT fields.

This never edits the canonical report, an earlier publication, Git, or a host.
The package gate and a human-approved report spec must already be complete.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import posixpath
import re
import sys

sys.dont_write_bytecode = True
import successor_evidence as evidence

FACT = re.compile(r'\{\{fact:([a-z][a-zA-Z0-9_]+)\}\}')
LOCAL_LINK = re.compile(r'\[([^\]]+)\]\((sandbox:/[^)]+)\)')
FORBIDDEN_CLAIM = '零遗忘'


def pointer(value, address):
    evidence.require(address.startswith('/'), 'RESULT pointer must be explicit')
    for part in address[1:].split('/'):
        part = part.replace('~1', '/').replace('~0', '~')
        value = value[int(part)] if isinstance(value, list) else value[part]
    evidence.require(value is None or isinstance(value, (str, int, float, bool)), 'report field is not scalar')
    return value


def formatted(value, mode):
    if mode == 'boolean_result':
        evidence.require(type(value) is bool, 'success rendering needs actual boolean')
        return 'PASS' if value else 'FAIL'
    if mode == 'integer':
        evidence.require(type(value) is int, 'integer field has different type')
        return str(value)
    if mode == 'seconds9':
        evidence.require(type(value) in {int, float} and value >= 0, 'invalid measured seconds')
        return f'{value:.9f}'
    evidence.require(mode == 'literal', 'unknown report field format')
    return str(value) if isinstance(value, str) else json.dumps(value, ensure_ascii=False)


def build(spec_path, output):
    spec_body, spec_pin = evidence.read(spec_path)
    spec = json.loads(spec_body)
    evidence.require(spec['state'] == 'READY_FOR_REVIEWED_FINAL_RENDER', 'draft report cannot be finalized')
    evidence.require(not output.exists(), 'report output must be a fresh directory')
    output.resolve().relative_to(evidence.ROOT)
    guards = spec['formal_documents_held']
    for row in guards:
        evidence.read(evidence.ROOT / evidence.safe(row['path']), row)

    cut_path = evidence.ROOT / evidence.safe(spec['evidence_freeze']['path'])
    cut = evidence.load(cut_path, spec['evidence_freeze'])
    package = evidence.load(evidence.ROOT / evidence.safe(spec['evidence_package_result']['path']), spec['evidence_package_result'])
    evidence.require(package.get('package_successful') is True, 'complete package restoration is required')
    evidence.require(package['freeze']['sha256'] == spec['evidence_freeze']['sha256'], 'package belongs to another cut')
    manifest_pin = next(row for row in cut['files'] if row['path'] == 'INPUT_MANIFEST.json')
    manifest = evidence.load(cut_path.parent / 'INPUT_MANIFEST.json', manifest_pin)
    retained = {row['workspace_path']: row for row in manifest['files']}
    baseline, by_identity = evidence.baseline()
    template_pin = spec['template']
    template_path = evidence.ROOT / evidence.safe(template_pin['path'])
    template_body, _ = evidence.read(template_path, template_pin)
    evidence.require(template_pin['path'] in retained and evidence.key(template_pin) == evidence.key(retained[template_pin['path']]), 'template is not in the frozen cut')
    text = template_body.decode('utf-8')
    evidence.require(FORBIDDEN_CLAIM not in text, 'do not replace the original retention threshold with a new zero threshold')

    facts, extracted = {}, []
    for binding in spec['fact_bindings']:
        identifier = binding['id']
        evidence.require(identifier not in facts, 'duplicate fact binding')
        original = binding['result']
        evidence.require(original['path'] in retained, 'actual fact RESULT is absent from the frozen cut')
        evidence.require(evidence.key(original) == evidence.key(retained[original['path']]), 'fact RESULT identity differs')
        value = pointer(evidence.load(evidence.ROOT / evidence.safe(original['path']), original), binding['pointer'])
        evidence.require(type(value) is type(binding['expected']) and value == binding['expected'], 'actual field changed; do not silently revise the report')
        facts[identifier] = formatted(value, binding['format'])
        extracted.append({'id': identifier, 'result': original, 'pointer': binding['pointer'],
                          'actual_value': value, 'rendered': facts[identifier]})
    evidence.require(set(FACT.findall(text)) == set(facts), 'missing or unused RESULT field binding')
    text = FACT.sub(lambda match: facts[match.group(1)], text)
    evidence.require('{{' not in text, 'unresolved draft field')

    supplied_refs = {row['path']: row for row in spec['references']}
    evidence.require(len(supplied_refs) == len(spec['references']), 'duplicate reference path')
    links = LOCAL_LINK.findall(text)
    wanted = {str(Path(url[len('sandbox:'):]).relative_to(evidence.ROOT)) for _, url in links}
    evidence.require(wanted == set(supplied_refs), 'template local links and exact reference list differ')
    output.mkdir(); publication = output / 'publication'; publication.mkdir()
    staged, references, substitutions, new_representations = {}, [], {}, {}
    report_repo_path = evidence.safe(spec['report_repository_path'])
    report_parent = posixpath.dirname(report_repo_path)
    new_prefix = evidence.safe(spec['new_reference_prefix'])
    old_paths = {row['path'] for row in baseline}
    for path in sorted(wanted):
        pin = supplied_refs[path]
        body, actual = evidence.read(evidence.ROOT / evidence.safe(path), pin)
        evidence.require(path in retained and evidence.key(actual) == evidence.key(retained[path]), 'reference is not retained by this cut')
        reused = by_identity.get(evidence.key(actual), [])
        partial = False
        if reused:
            row = sorted(reused, key=lambda item: item['path'])[0]
            repo_path = row['path']
            storage = {'kind': 'existing_repository_file', 'file': evidence.blob_row(row)}
        else:
            name = actual['sha256'][:20] + '-' + Path(path).name
            repo_path = new_prefix + '/' + name
            if repo_path in new_representations:
                representation = new_representations[repo_path]
            else:
                representation = evidence.stage_bytes(publication, repo_path, body, staged)
                new_representations[repo_path] = representation
            storage = {'kind': 'new_exact_bytes', 'representation': representation}
            if representation['encoding'] != 'identity':
                partial = True
                repo_path = new_prefix + '/' + name + '.REASSEMBLY.json'
                if repo_path not in staged:
                    evidence.stage_bytes(publication, repo_path, evidence.encoded(representation), staged)
            evidence.require(repo_path not in old_paths, 'new reference would overwrite an old599 file')
            evidence.require(evidence.restore_representation(representation, lambda item: evidence.read(publication / evidence.safe(item['path']), item)[0]) == body, 'new reference does not restore exactly')
        substitutions['sandbox:' + str(evidence.ROOT / path)] = (posixpath.relpath(repo_path, report_parent), partial)
        references.append({'workspace_path': path, **actual, 'link_repository_path': repo_path,
                           'link_is_reassembly_descriptor': partial, 'storage': storage})

    def replace_link(match):
        target, partial = substitutions[match.group(2)]
        suffix = '（此链接为原件的可逆分片索引）' if partial else ''
        return f'[{match.group(1)}]({target})' + suffix

    published_text = LOCAL_LINK.sub(replace_link, text)
    evidence.require('sandbox:' not in published_text and FORBIDDEN_CLAIM not in published_text, 'publication retains unresolved local link or new retention threshold')
    report_data = published_text.encode('utf-8')
    evidence.require(len(report_data) <= evidence.MAX_FILE, 'report exceeds original per-file bound')
    evidence.stage_bytes(publication, report_repo_path, report_data, staged)
    reference_repo_path = evidence.safe(spec['reference_manifest_repository_path'])
    reference_body = evidence.encoded({'state': 'EXACT_REFERENCES_FOR_SEPARATE_FINAL_REPORT_CANDIDATE',
        'report': {'path': report_repo_path, **evidence.identity(report_data)}, 'references': references,
        'actual_fields': extracted, 'report_spec': spec_pin, 'evidence_freeze': spec['evidence_freeze'],
        'no_qualification_inferred_from_package_or_component_success': True})
    evidence.require(len(reference_body) <= evidence.MAX_FILE, 'reference manifest requires a separate reviewed representation')
    evidence.stage_bytes(publication, reference_repo_path, reference_body, staged)
    for path, row in staged.items():
        evidence.require(row['bytes'] <= evidence.MAX_FILE and path not in old_paths, 'new report publication overwrites an old599 path or exceeds bound')
        evidence.read(row['local_path'], row)
    for row in guards:
        evidence.read(evidence.ROOT / evidence.safe(row['path']), row)
    evidence.put(output / 'REPORT_SPEC.json', spec_body)
    evidence.put(output / 'LOCAL_REPORT_CANDIDATE.md', text.encode('utf-8'))
    evidence.put(output / 'PUBLICATION_FILES.json', evidence.encoded({'files': sorted(staged.values(), key=lambda row: row['path']),
        'baseline599_unchanged': True, 'canonical_report_unchanged': True, 'git_publication_executed': False}))
    result = {'state': 'SEPARATE_REPORT_CANDIDATE_RENDERED_ALL_REFERENCES_CHECKED',
              'report': evidence.identity(report_data), 'references': len(references),
              'actual_result_fields': len(extracted), 'new_publication_files': len(staged),
              'canonical_or_prior_publication_writes': 0, 'host_native_model_git_actions': 0}
    evidence.put(output / 'RESULT.json', evidence.encoded(result))
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--spec', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    print(json.dumps(build(args.spec, args.output), ensure_ascii=False))
