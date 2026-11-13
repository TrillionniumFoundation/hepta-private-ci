"""Seal reviewer-owned observations only; no project source or tool execution."""
from pathlib import Path
import hashlib
import json

D = Path('/tmp/hepta-36fa-e2-registration-independent-review-v1')
M = Path('/tmp/hepta-36fa-e2-declaration-metadata-increment-v1')
S = Path('/tmp/hepta-36fa-root-product-e2-proposal-v1/registration-components-frozen-v2')


def pin(raw):
    return {'bytes': len(raw), 'sha256': hashlib.sha256(raw).hexdigest(),
            'git_blob': hashlib.sha1(b'blob ' + str(len(raw)).encode() + b'\0' + raw).hexdigest()}


def identity(path):
    return {'path': str(path), **pin(path.read_bytes())}


def save(path, obj):
    raw = (json.dumps(obj, sort_keys=True, ensure_ascii=False, indent=2) + '\n').encode()
    with path.open('xb') as f:
        f.write(raw)
    return pin(raw)


proof = json.loads((D / 'BYTE_AND_SOURCE_PROOF.json').read_bytes())
relation = json.loads((D / 'RELATION_AND_UNION_PROOF.json').read_bytes())
metadata = json.loads((M / 'MATCH_AND_INVERSE_PROOF.json').read_bytes())

review = {
    'format': 'hepta-independent-e2-registration-components-review-v1',
    'reviewer': 'native_ci_audit',
    'status': 'STATIC_COMPONENT_REVIEW_COMPLETE_WITH_SEPARATE_METADATA_CORRECTION_AND_KNOWN_TEST_SOURCE_CORRECTION',
    'not_execution_or_qualification_approval': True,
    'fixed_component': identity(S / 'MANIFEST.json'),
    'baseline': proof['base_callers'],
    'isolated_E1_E2_projection': proof['projection'],
    'scope': [
        'All nine manifest payloads and the four bounded ASCII parts were read in full and independently hashed.',
        'All 12 frozen source packets were independently composed into 67 E2 own paths. Six existing shared paths use the exact Root-v6 body already named in SOURCE_PINS; the explicit UFCS handoff uses its final E2 image.',
        'The complete 19 text splices were applied and reversed byte for byte, and the entire before/after TOML was parsed with the standard library.',
        'The explicit production function inventory was independently re-enumerated as fixed text: exactly 157 new declaration keys relative to their first E2 before-images.',
        'All 94 listed new-boundary caller pairs and all 15 appended old-boundary caller pairs have concrete matching call sites; receiver/field/UFCS anchors were independently inspected.',
        'Root union seed was cross-checked only for the E3/E2 row slices and additive old-caller overlap. It remains an incomplete final registration.'
    ],
    'findings': [
        {
            'id': 'E2_DECLARATION_METADATA_STALE',
            'severity': 'concrete review-metadata defect',
            'original': identity(S / 'DECLARATION_DISPOSITIONS.json'),
            'description': 'The original 157-row disposition list reused an earlier declaration draft. Ten records do not give the body/span of the existing whole_source_required target: four have changed body/identity and six have offset-only changes.',
            'body_changes': [x for x in metadata['changes'] if x['body_changed']],
            'offset_changes': [x for x in metadata['changes'] if not x['body_changed']],
            'impact': 'The affected records cannot be used as exact current function-byte evidence. The final full-source pins and required full-file strings are separately correct; this defect did not change the registered source or broaden caller permissions.',
            'successor': identity(M / 'MANIFEST.json'),
            'successor_after': identity(M / 'DECLARATION_DISPOSITIONS.after.json'),
            'successor_proof': identity(M / 'MATCH_AND_INVERSE_PROOF.json'),
            'successor_status': 'Prepared locally at explicit Root instruction; all 157 declarations uniquely match their exact target source. Only body/start/end/identity change in ten rows, and reversal restores the full original metadata bytes. Root integration/review remains separate.'
        },
        {
            'id': 'MATERIAL_TEST_MISSING_CLOSING_BRACE_PREVIOUSLY_REPORTED',
            'severity': 'known concrete source syntax defect in frozen predecessor',
            'description': 'The e120 test source named by this component ends without the last test function closing brace. The original frozen v2 component therefore does not by itself describe a compilable corrected test source.',
            'original_test': {'bytes': 7528, 'git_blob': '1c8ea95921a5846f3d7c02dd7591c04b8e3a9320', 'sha256': 'e74caced8e82f45ca2b64b34b33aa5adcccec97062fe474e26991a04d7199633'},
            'independent_review': identity(Path('/tmp/hepta-36fa-material-source-tests-independent-review-v1/REVIEW.json')),
            'separate_fix_packet': {'bytes': 16205, 'git_blob': '0cefd50845cb790b581553b47e84bdcdb1015e91', 'sha256': '1164b9a6a15407ca463912e54ca65a667e695349d7f33fe5485b3c71c15c4471'},
            'separate_fix_review': identity(Path('/tmp/hepta-36fa-material-source-tests-independent-review-v1/CLOSURE_INCREMENT_REVIEW.json')),
            'resolution_boundary': 'Exactly the original 7528-byte prefix plus } and LF, independently checked. No test was executed. Root must include this independent source layer in its final source map; this review does not rewrite the old component.'
        }
    ],
    'other_concrete_static_blockers_found': [],
    'preservation': {
        '650_existing_boundaries': 'Every field except the specified 12 ordered caller-list appends is identical. Fifteen appended paths are disjoint from the old lists; no original caller is removed or reordered.',
        '451_existing_protected_rows': 'All old rows remain in order, including duplicate paths. Only seven required strings in five rows change. All forbidden strings, authority/literal fields, function-order rules, top-level requirements and flags are identical.',
        'specific_rows': 'Protected row 411 and original feature-control row 198 are wholly identical. Original feature required markers and ordered sequences remain present in the reviewed MAX-strengthened source.',
        'new_rows': '91 new boundaries and 61 exact full-file required guards are appended. All old required boundary IDs remain an ordered prefix and the 91 new IDs append in the same order.',
        'authority': 'Every authority field remains false. ignored_path_fragments remains exactly /tests/, /examples/, _tests.rs. No new extension or path exclusion is introduced.',
        'full_text': 'All 19 unique forward and reverse replacements exactly match the complete 1,902,614-byte baseline and 2,553,531-byte E1+E2 projection.',
        'bounded_representation': 'Three oversized raw artifacts are exactly recovered from four strict base64+LF parts. Part offsets, decoded gzip identity, raw identity and local original bytes all match. Maximum part 262,145 bytes; no raised storage bound.'
    },
    'typed_relationship_review': {
        'explicit_boundaries': '86 of the 157 new public/crate/super function declarations map to explicit E2 rows. The remaining five new rows are the two OriginalRootLaneFactory and three OriginalRootCellPump sealed trait methods; their sole private implementations are in the same guarded source.',
        'old_appends': 'UFCS preserves distinctions between OriginalRootInitialGenerationCustodyV1 and OriginalRootCircuitTaskCustodyV1. The seal_bootstrap successor explicitly names the same PreparedHostAuthoritySession. The old regex and old boundary semantics remain unchanged.',
        'same_source_and_cell': 'Root runtime/bootstrap/source handoff methods retain the original typed factory, source and Cell pump. Corresponding listed callers are the exact private bridge/loan/config methods inspected in the earlier frozen production reviews.',
        'generic_method_disambiguation': 'The pure first pass records lexical candidates; the supplemental pass selects concrete OriginalTaskHostLanes::serve versus remote::serve, DaemonCellPort/DaemonLoans/ReverseClient/Budget/Lane constructors, and the second take on Option<Box<dyn OriginalRootLaneFactory>>. Generic same-name hits are not counted as authority edges.',
        'material_read': 'The optional existing call_pattern matches exactly the two private OriginalReadback::RootMaterial arms in circuit_task_source_readback.rs. The enum contains Arc<material::Client>; the pattern does not authorize arbitrary Client::read.',
        'five_rejected_false_receivers': [
            'DaemonLoans::attach is not AgentdProductionOperationRuntimeConfig::attach.',
            'The Lane-owned HostAuthorityPeerChannel::exchange is not RootAdminCapability::exchange.',
            'The private connect helper and tokio UnixStream::connect are not RootLearningHandoffV1::connect.',
            'The private per-channel Budget::begin is not RootResidentLearningEffectGateV3::begin.',
            'DaemonLoans::respond is not OriginalVersionLocalReadBindingV1::respond.'
        ],
        '70_other_declarations': 'All 70 full helper bodies were read. They are bounded data codecs, immutable admission metadata getters, deadline checks or error projections inside existing private module closures. Decoded CellDecisionReceiptV1 explicitly has AuthorityPosture::DENY_ALL; byte canonicality is not mistaken for signature authentication or owner authority. The helpers do not return live source writers, original receipts capable of admission, Root grants, Config/Store replacement authority, or a replacement Cell pump.',
        'old_execute': 'The one separately classified Driver::execute body is an exact original body even though its impl generic port context changed; the complete reviewed production file is still required.',
        'limits': 'This is static source/field/UFCS review of the finite frozen view. It does not assert that a Rust compiler or the unchanged project typed collector accepted these relations or that future loader callers are already registered.'
    },
    'test_registration_review': {
        'root_parent_candidates': relation['tests']['root_parents'],
        'ordinary_tests': relation['tests']['ordinary_linux_tests'],
        'separate_feature_test': relation['tests']['separate_clock_regression'],
        'root_semantics': 'The two ignored factory cases retain the same original Root fixture and real generation custody. They check that an unstarted task cannot become Source completion and that a mismatched task fence retains only the same failed-operation handle/journal. They do not execute a cross-process task lane.',
        'ordinary_semantics': 'Four bootstrap/receipt cases and three Material content cases are separately reviewed source proposals; the Material syntax successor is necessary. The clock case keeps the original unresolved dispatch after a worker completes with an invalid clock. None were run.',
        'workflow': 'The component proposes two additional Root parents but does not modify a runner/workflow, budgets or filters. Existing Root parents cannot be dropped during final integration. Native selected/executed counts remain unknown.'
    },
    'root_union_seed_cross_check': relation['root_union_seed'],
    'final_integration_obligations': [
        'Apply the separate ten-record metadata correction and the separate Material test closing-brace successor without overwriting frozen predecessors.',
        'Include later loader and pre-freeze exact source/caller layers; empty product_callers in this component are statements only about this frozen E2 view.',
        'Rebind shared full-file required strings to the final reviewed combined source once; preserve every E1/E3/E2 guard row and do not deduplicate by path.',
        'Refresh final complete inventory, source-contract hashes/counts, allowlist digest, QA expected IDs/counts and the full Root-parent workflow union from the final bytes.',
        'Required whole-source strings prove presence of that exact text; they alone do not forbid an appended extra impl/getter. Preserve and run the unchanged full source/shape/typed checks only under later explicit authorization.',
        'The 757-boundary/531-guard seed is not the final loader-inclusive registration and is not a source-gate PASS.'
    ],
    'reviewer_failures_preserved': [
        'One initial interactive schema-summary inspection assumed all JSON roots were objects; DECLARATION_DISPOSITIONS is a list. This was an inspection-format error, not an input defect.',
        'review_bytes.py first expected the five abstract trait rows to have zero concrete function bodies. The fixed source also contains their sole private trait implementations, so that reviewer assertion exited 1. The original script and actual EXECUTION_01 are preserved; review_bytes_v2 requires those private implementations plus the exact trait declaration and exits 0. Candidate bytes were untouched.'
    ],
    'reproducible_evidence': [identity(D / n) for n in ['review_bytes.py', 'review_bytes_v2.py', 'REVIEWER_ASSUMPTION_CORRECTION.patch', 'EXECUTION_01.original.json', 'EXECUTION_02.original.json', 'BYTE_AND_SOURCE_PROOF.json', 'review_relations.py', 'RELATION_EXECUTION_01.original.json', 'RELATION_AND_UNION_PROOF.json']],
    'execution': {'reviewer_standard_library_byte_scripts_only': True, 'author_scripts_run': False,
                  'project_modules_imported': False, 'collector': False, 'QA': False, 'Rust': False,
                  'H': False, 'source_git_write': False, 'source_ref_write': False,
                  'actual_git_create_or_get_by_reviewer': False},
    'publication': 'Local immutable files with computed identities, for Root independent review and archival. No runtime or qualification result is asserted.'
}
report_pin = save(D / 'REVIEW.json', review)
names = ['review_bytes.py', 'review_bytes_v2.py', 'REVIEWER_ASSUMPTION_CORRECTION.patch',
         'EXECUTION_01.original.json', 'EXECUTION_02.original.json', 'BYTE_AND_SOURCE_PROOF.json',
         'review_relations.py', 'RELATION_EXECUTION_01.original.json', 'RELATION_AND_UNION_PROOF.json',
         'seal_review.py', 'REVIEW.json']
files = [dict(path=n, **pin((D / n).read_bytes())) for n in names]
assert max(x['bytes'] for x in files) <= 512000
index_pin = save(D / 'CLOSED_FILE_INDEX.json', {'format': 'hepta-e2-registration-independent-review-closed-index-v1',
                                             'files': files, 'computed_only': True,
                                             'separate_metadata_manifest': identity(M / 'MANIFEST.json')})
print(json.dumps({'review': report_pin, 'index': index_pin, 'payloads': len(files),
                  'max_leaf': max(x['bytes'] for x in files)}, indent=2))
