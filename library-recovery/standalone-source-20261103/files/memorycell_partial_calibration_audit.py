"""Read-only independent audit of two genuine Qwen calibration-shard artifacts.

These five model answers are part of *previously exposed calibration tasks*;
there is NO frozen k, no evaluation-task answer and no qualification. The
artifacts belong to one exact GitHub commit and may not be mixed with any
later canonical-stage run. Requires only Python standard library.
"""

from __future__ import annotations

import argparse
from hashlib import sha256
import json
import math
from pathlib import Path, PurePosixPath
import re
import stat
import zipfile

SCHEMA = "hepta.memory-strong-rag.partial-calibration-independent-audit.v1"
MODEL = "f9aa334d3a02cabececea367c283caf66ef9875132907ebc34dac1c8d3a7f225"
SOURCE_COMMIT = "db7c31c90ad4eb7cf902c432a355c8302b0dffc2"
PLAN_SHA = "42417d57f72132d6403857843683f0e0497c17be5fb59c6afc2f2b25905cf031"
SHARDS = (
    ("qwen-case0-part0-11707168275.zip", "6edbb96edc7b783ddf6148b0c030e7d0ad63bfe9eec273a551bf9268d6ec7f90", 0, 0, ("k1", "k3", "k6"), 11707168275),
    ("qwen-case2-part1-11707620762.zip", "87f0358d2845a933866fe67ca6d4a0c08043327a0cdc9b3ad7b11848f3acf040", 2, 1, ("k2", "k4"), 11707620762),
)
PREP = ("qwen-calibration-public-11707090232.zip", "ae58c43d6b5d5a39dc428e6f22b6df925e715d44307fa407f3620bec22b97904")
LABELS = ("qwen-calibration-labels-11706825892.zip", "ea34d5dd7d900fa94d0c8a11729fabdccee57911a1f4c658d5ee2ffaf922eccf")
STAGE_FIELDS = ("tier", "repository", "revision", "inventory_sha256", "publisher_sha256", "model_file_bytes", "research_only", "production_accepted")
GRAMMAR = re.compile(r"\s*((?:site|mode)_[0-9a-f]{8})(?:\s*\[E[1-9][0-9]*\])*\s*\.?\s*")
EXTRACT = re.compile(r"\[E([1-9][0-9]*)\]")


def sha(data: bytes) -> str:
    return sha256(data).hexdigest()


def canonical(value) -> str:
    return sha(json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":")).encode())


def parse(data: bytes):
    def unique(pairs):
        obj = {}
        for key, val in pairs:
            if key in obj:
                raise ValueError("duplicate JSON key")
            obj[key] = val
        return obj
    def nonfinite(value):
        raise ValueError("nonfinite JSON value: " + value)
    return json.loads(data.decode("utf-8"), object_pairs_hook=unique, parse_constant=nonfinite)


def unzip_strict(path: Path, expected_sha: str, *, max_bytes=1_000_000):
    if path.is_symlink() or not path.is_file():
        raise ValueError("regular source artifact required")
    raw = path.read_bytes()
    if len(raw) > max_bytes or sha(raw) != expected_sha:
        raise ValueError("GitHub artifact outer SHA differs")
    files = {}
    with zipfile.ZipFile(path) as archive:
        infos = archive.infolist()
        if not 1 <= len(infos) <= 16 or sum(x.file_size for x in infos) > 3_000_000:
            raise ValueError("unbounded archive")
        for entry in infos:
            name = PurePosixPath(entry.filename)
            if (entry.is_dir() or name.is_absolute() or '..' in name.parts
                    or '\\' in entry.filename or len(name.parts) != 1
                    or stat.S_ISLNK(entry.external_attr >> 16)
                    or str(name) in files):
                raise ValueError("unsafe or duplicate ZIP member")
            files[str(name)] = archive.read(entry)
    return files


def audit(root: Path):
    prep = unzip_strict(root / PREP[0], PREP[1])
    labels_zip = unzip_strict(root / LABELS[0], LABELS[1])
    if set(prep) != {"calibration-plan.json", "calibration-sources.json"} or set(labels_zip) != {"calibration-labels.json"}:
        raise ValueError("unregistered calibration inputs")
    if sha(prep['calibration-plan.json']) != PLAN_SHA:
        raise ValueError("public calibration plan changed")
    manifest = parse(prep['calibration-plan.json'])
    if (manifest['source_commit'] != SOURCE_COMMIT or not manifest['calibration_only']
            or manifest['test_cases_materialized'] or len(manifest['cases']) != 8
            or tuple(manifest['ks']) != (1, 2, 3, 4, 6)):
        raise ValueError("changed calibration-only census")
    if (manifest['calibration_labels_sha256'] != sha(labels_zip['calibration-labels.json'])
            or manifest['calibration_sources_sha256'] != sha(prep['calibration-sources.json'])):
        raise ValueError("calibration source/answer identity changed")
    cases = manifest['cases']
    targets = {v['id']: v for v in parse(labels_zip['calibration-labels.json'])}
    originals = {v['identity']: v for v in parse(prep['calibration-sources.json'])}
    if len(targets) != 8 or len(originals) != 54:
        raise ValueError("wrong complete authored calibration population")
    source_pins = set()
    stage_sha_orig = set()
    canonical_stage_sha = set()
    identities = set()
    rows_out = []
    for zip_name, outer, index, half, arms, artifact_id in SHARDS:
        files = unzip_strict(root / zip_name, outer)
        expected = {"runtime-preflight.json", "stage.json", "inventory.json", "publisher.json", "raw-answers.jsonl", "run.json", "sha-pins.json"}
        if set(files) != expected:
            raise ValueError("shard file census changed")
        pins = parse(files['sha-pins.json'])
        if set(pins) != expected - {"sha-pins.json"} or any(sha(files[f]) != digest for f, digest in pins.items()):
            raise ValueError("unsealed or changed original shard content")
        run, stage = parse(files['run.json']), parse(files['stage.json'])
        inventory = parse(files['inventory.json'])
        if (run['schema'] != 'hepta.memory-strong-rag.shards.v1'
                or run['phase'] != 'calibration' or run['source_commit'] != SOURCE_COMMIT
                or run['case_index'] != index or run['part'] != half
                or run['arms'] != list(arms) or run['generated'] != len(arms)
                or run['calibration_plan_sha256'] != PLAN_SHA
                or run['model_stage_sha256'] != pins['stage.json']
                or run['raw_answers_sha256'] != pins['raw-answers.jsonl']
                or run['production_accepted'] is not False or run['model_weight_training'] is not False):
            raise ValueError("shard provenance or model training flag changed")
        if (stage['tier'] != 'qwen-3b' or stage['revision'] != '82f42baa094a9600e39ccd80d34058aeeb3abbc1'
                or stage['repository'] != 'Qwen/Qwen2.5-3B-Instruct'
                or stage['inventory_sha256'] != pins['inventory.json']
                or stage['publisher_sha256'] != pins['publisher.json']
                or inventory['inventory_digest'] != MODEL
                or run['reader_identity'] != MODEL or stage['production_accepted'] is not False
                or type(stage['seconds']) not in (int, float) or not math.isfinite(stage['seconds'])):
            raise ValueError("reader inventory/revision/host timing changed")
        stage_sha_orig.add(pins['stage.json'])
        model_stage = {k: v for k, v in stage.items() if k != 'seconds'}
        if set(model_stage) != set(STAGE_FIELDS):
            raise ValueError("unregistered canonical reader metadata")
        canonical_stage_sha.add(sha((json.dumps(model_stage, ensure_ascii=False, indent=2, allow_nan=False)+'\n').encode()))
        source_pins.add((pins['inventory.json'], pins['publisher.json'], run['reader_identity']))
        if not files['raw-answers.jsonl'].endswith(b'\n'):
            raise ValueError("unfinished answer journal")
        lines = files['raw-answers.jsonl'].splitlines()
        if len(lines) != len(arms):
            raise ValueError("missing executed answer")
        case = cases[index]
        qid = case['query']['identity']
        if run['case_id'] != qid or run['generated'] != len(lines):
            raise ValueError("misbound original case")
        for item, arm in zip(lines, arms, strict=True):
            row = parse(item)
            expected_sel = case['candidate_ids'][:int(arm[1:])]
            if (row['question_id'] != qid or row['arm'] != arm or row['kind'] != case['kind']
                    or row['status'] != 'succeeded' or row['selected'] != expected_sel
                    or row['candidate_digest'] != case['candidate_digest']
                    or row['receipt']['reader_identity'] != MODEL
                    or row['receipt']['trainable_parameters'] != 0
                    or row['receipt']['production_accepted'] is not False
                    or row['receipt']['answer_postprocessed'] is not False
                    or row['receipt']['query_digest'] != canonical(case['query'])
                    or row['receipt']['token_limit'] != 2048
                    or not 0 < row['receipt']['input_tokens'] <= 2048
                    or not 0 < row['receipt']['generated_tokens'] <= 64):
                raise ValueError("answer or frozen retrieval drift")
            delivered = row['receipt']['delivered_evidence']
            if len(delivered) != len(expected_sel):
                raise ValueError("missing delivered original evidence")
            for i, (entry, source_id) in enumerate(zip(delivered, expected_sel, strict=True), 1):
                doc = originals[source_id]
                if (entry['label'] != f'E{i}' or entry['original_id'] != source_id
                        or entry['root'] != doc['root'] or entry['scope'] != doc['scope']
                        or entry['excerpt'] != doc['content']
                        or entry['source_digest'] != canonical(doc['content'])
                        or entry['source_start'] != 0
                        or entry['source_end'] != len(doc['content'].encode())):
                    raise ValueError("delivered evidence not original source bytes")
            derivations = row['receipt']['derived_evidence']
            if len(derivations) != len(delivered):
                raise ValueError("derived evidence census differs from original")
            for i, (d, entry, source_id) in enumerate(zip(derivations, delivered, expected_sel, strict=True), 1):
                event = parse(originals[source_id]['content'].encode())
                parent_ids = ", ".join(event['supersedes']) or "none explicitly named"
                expected_text = (
                    f"Event {event['id']}: at logical revision {event['revision']}, "
                    f"entity {event['entity']} has attribute {event['attribute']} "
                    f"with value {event['value']}. Superseded event IDs: {parent_ids}. "
                    "This is a logical state revision, not a calendar date."
                )
                if (d['label'] != f'E{i}' or d['original_id'] != source_id
                        or d['original_digest'] != canonical(originals[source_id]['content'])
                        or d['text'] != expected_text
                        or d['derivation_profile'] != 'hepta.controlled-event.schema-expansion.v1'):
                    raise ValueError("derived text fabricated or detached from original JSON")
            request = row['citation_audit']['request']
            if (request['answer'] != row['answer'] or request['query_id'] != qid
                    or request['question'] != case['query']['content']
                    or request['prompt_digest'] != row['receipt']['input_ids_digest']
                    or row['citation_audit']['judgement'] is not None
                    or len(request['sources']) != len(delivered)
                    or any(request['sources'][i]['excerpt'] != delivered[i]['excerpt'] or
                           request['sources'][i]['label'] != delivered[i]['label'] or
                           request['sources'][i]['id'] != delivered[i]['id']
                           for i in range(len(delivered)))):
                raise ValueError("citation queue detached from Qwen output")
            truth = targets[qid]
            match = GRAMMAR.fullmatch(row['answer'])
            parsed = match[1] if match else None
            support = set(truth['support'])
            correct = parsed == truth['expected']
            support_covered = support.issubset(expected_sel)
            cited_ids = {delivered[int(j)-1]['original_id'] for j in EXTRACT.findall(row['answer']) if 1 <= int(j) <= len(delivered)}
            receipts = row['receipt']
            if ((qid, arm) in identities or type(receipts['seconds']) not in (int,float)
                    or not math.isfinite(receipts['seconds']) or receipts['seconds'] < 0):
                raise ValueError("duplicate attempt or invalid real runtime")
            identities.add((qid, arm))
            rows_out.append(dict(
                case_index=index, case_id=qid, kind=truth['kind'], arm=arm,
                status='succeeded', strict_task_success=correct,
                required_sources_in_context=support_covered,
                annotation_support_in_citations=support.issubset(cited_ids),
                answer= row['answer'], parsed_identifier=parsed,
                selected_ids=expected_sel, input_tokens=receipts['input_tokens'],
                generated_tokens=receipts['generated_tokens'], reader_seconds=receipts['seconds'],
                original_model_sha256=pins['inventory.json'], source_commit=SOURCE_COMMIT,
                workflow_run_id=38150189865, artifact_id=artifact_id,
            ))
    if len(rows_out) != 5 or len(source_pins) != 1 or len(stage_sha_orig) != 2 or len(canonical_stage_sha) != 1:
        raise ValueError("unexpected incomplete/host-varying source census")
    return dict(
        schema=SCHEMA, source_commit=SOURCE_COMMIT, generating_run_id=38150189865,
        archived_shards=2, original_calibration_shard_population=16,
        observed_model_calls=len(rows_out), preregistered_calibration_calls=40,
        sampled_test_cases=0, complete_calibration=False,
        qualifying_result=False, source_inventory_pins_agree=True,
        raw_host_stage_pins_differ=True,
        canonical_model_stage_sha256=next(iter(canonical_stage_sha)),
        canonicalization_removes_only_host_download_seconds=True,
        distinct_original_stage_hashes=sorted(stage_sha_orig),
        model_identity=MODEL, plan_sha256=PLAN_SHA,
        strict_success=sum(x['strict_task_success'] for x in rows_out),
        required_sources_in_context=sum(x['required_sources_in_context'] for x in rows_out),
        annotation_support_in_citations=sum(x['annotation_support_in_citations'] for x in rows_out),
        total_input_tokens=sum(x['input_tokens'] for x in rows_out),
        total_model_seconds=sum(x['reader_seconds'] for x in rows_out),
        observations=rows_out,
        independent_human_semantic_review=False,
        predictive_validity_established=False,
        production_accepted=False,
    )


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', nargs='?', type=Path, default=Path('/mnt/data'))
    parser.add_argument('--output', type=Path, default=Path('/mnt/data/memorycell_partial_calibration_verified.json'))
    args = parser.parse_args()
    result = audit(args.directory)
    with args.output.open('x', encoding='utf-8') as stream:
        json.dump(result, stream, indent=2, ensure_ascii=False, allow_nan=False)
        stream.write('\n')
    print(json.dumps({k:v for k,v in result.items() if k!='observations'},indent=2))

if __name__ == '__main__':
    main()
