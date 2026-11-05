//! Signed native empirical evidence, shared-source budgets and durable rollback.
//! The positive fixture deliberately memorizes the installed public historical rows.
//! Its success tests admission mechanics, never prospective model improvement.
use serde_json::{json, Value};
use std::{fs, path::Path};
use trnm_crypto_primitives::{sign_hex, signing_key_from_hex};
use trnm_mvcc_fee::{
    continuity_v1, integer_factor_candidate_v2 as factor, model_evidence_v3 as model_evidence,
    pon_executor::{self, Config, State},
    public_evaluation as evaluation,
};
use trnm_pon_node::{
    development_public, NativeBudgetLaneV1, NativeBudgetRequestV1, NativeContributionClaimV1, Node,
    Settings,
};
use trnm_protocol::{
    integer_factor_v2::FactorWitnessV2,
    pon_wire::{hash, Envelope, Hash},
};

const POSITIVE_SCORE: u64 = 240_000;
const CLOCK: u64 = 1_800_100_000;

fn cfg() -> Config {
    Config::installed_with_model_profiles(
        evaluation::PROFILE,
        "legacy-task-v1",
        model_evidence::PROFILE,
    )
    .unwrap()
}
fn settings() -> Settings {
    Settings::development_with_model_profiles(
        None,
        evaluation::PROFILE,
        "legacy-task-v1",
        model_evidence::PROFILE,
    )
    .unwrap()
}
fn signed(c: &Config, who: u64, account_sequence: u64, tag: u8, payload: Vec<u8>) -> Vec<u8> {
    let key =
        signing_key_from_hex(&hex::encode(hash(b"DEV-ONLY-KEY", &[&who.to_le_bytes()]))).unwrap();
    let mut transaction = Envelope {
        network: c.network,
        sender: development_public(who).unwrap(),
        nonce: account_sequence,
        expiry: 2000,
        fee_limit: 1_000_000,
        tag,
        payload,
        signature: [0; 64],
    };
    transaction.signature = hex::decode(sign_hex(&key, &transaction.signing_digest().unwrap()))
        .unwrap()
        .try_into()
        .unwrap();
    transaction.encode().unwrap()
}
fn next_nonce(state: &State, who: u64) -> u64 {
    state[&format!("account:{}", hex::encode(development_public(who).unwrap()))]["nonce"]
        .as_u64()
        .unwrap()
        + 1
}
fn object(state: &State, cid: Hash) -> &Value {
    &state[&format!("contribution:{}", hex::encode(cid))]
}
fn read_hash(value: &Value) -> Hash {
    hex::decode(value.as_str().unwrap())
        .unwrap()
        .try_into()
        .unwrap()
}

/// Five deterministic multiclass perceptron passes over the public policy rows.
/// Subtracting row zero preserves argmax and gives the actual rank-two factors
/// B=[[0,0],[1,0],[0,1]], A=[row1-row0,row2-row0]. Scaling changes BA, not labels.
fn memorizing_factors(scale: i16) -> Vec<i16> {
    let policy: Value = serde_json::from_str(include_str!(
        "../../../../config/pon/model-evidence-v3.json"
    ))
    .unwrap();
    let tasks = policy["tasks"].as_array().unwrap();
    assert_eq!(tasks.len(), 25);
    let mut weights = vec![vec![0_i16; 257]; 3];
    for _ in 0..5 {
        for task in tasks {
            let x: Vec<i16> = task["features"]
                .as_array()
                .unwrap()
                .iter()
                .map(|value| i16::try_from(value.as_i64().unwrap()).unwrap())
                .collect();
            assert_eq!(x.len(), 257);
            let scores: Vec<i64> = weights
                .iter()
                .map(|row| {
                    row.iter()
                        .zip(&x)
                        .map(|(&w, &f)| i64::from(w) * i64::from(f))
                        .sum()
                })
                .collect();
            let mut prediction = 0;
            for i in 1..3 {
                if scores[i] > scores[prediction] {
                    prediction = i;
                }
            }
            let target = usize::try_from(task["label"].as_u64().unwrap()).unwrap();
            if prediction != target {
                for (i, feature) in x.into_iter().enumerate() {
                    weights[prediction][i] -= feature;
                    weights[target][i] += feature;
                }
            }
        }
    }
    let mut factors = vec![0, 0, 1, 0, 0, 1];
    for row in weights.iter().skip(1) {
        factors.extend(
            row.iter()
                .zip(&weights[0])
                .map(|(&coefficient, &base)| (coefficient - base) * scale),
        );
    }
    factors
}
fn build(
    state: &State,
    c: &Config,
    who: u64,
    coefficients: Vec<i16>,
    root: Hash,
) -> FactorWitnessV2 {
    let rank = if coefficients.len() == 520 { 2 } else { 1 };
    factor::build_witness(
        state,
        c,
        development_public(who).unwrap(),
        0,
        factor::FactorInputV2 {
            slot: 0,
            rank,
            coefficients,
        },
        root,
    )
    .unwrap()
}
fn record_context(c: &Config, label: &str) {
    if let Some(directory) = std::env::var_os("MODEL_EVIDENCE_V3_EVIDENCE_DIR") {
        let directory = Path::new(&directory).join(label);
        fs::create_dir_all(&directory).unwrap();
        fs::write(
            directory.join("context.json"),
            serde_json::to_vec(&json!({
                "network":hex::encode(c.network),
                "parameters":hex::encode(c.parameters),
                "family":hex::encode(c.family),
                "plan":hex::encode(c.plan),
                "params":c.params,
                "fixture":"deliberate-public-row-memorization; no prospective efficacy claim"
            }))
            .unwrap(),
        )
        .unwrap();
    }
}
fn append(
    node: &mut Node,
    parent: Hash,
    height: u64,
    transactions: Vec<Vec<u8>>,
    label: &str,
) -> Hash {
    assert_eq!(node.parent_height(parent).unwrap() + 1, height);
    let packet = node
        .make(
            parent,
            transactions,
            development_public(3).unwrap(),
            1_800_000_000 + height * 10,
            4096,
        )
        .unwrap();
    let id = node.admit(&packet, CLOCK).unwrap();
    node.activate(id).unwrap();
    if let Some(directory) = std::env::var_os("MODEL_EVIDENCE_V3_EVIDENCE_DIR") {
        let directory = Path::new(&directory).join(label);
        fs::create_dir_all(&directory).unwrap();
        fs::write(
            directory.join(format!("packet-{height:03}-{}.pnw1", hex::encode(id))),
            packet.encode().unwrap(),
        )
        .unwrap();
        fs::write(
            directory.join(format!("state-{height:03}.json")),
            serde_json::to_vec(&node.state_at(id).unwrap()).unwrap(),
        )
        .unwrap();
    }
    id
}
fn refusal(node: &Node, parent: Hash, height: u64, transaction: Vec<u8>, expected: &str) {
    let before = node.read_active().unwrap();
    let error = node
        .make(
            parent,
            vec![transaction],
            development_public(3).unwrap(),
            1_800_000_000 + height * 10,
            4096,
        )
        .unwrap_err();
    assert!(error.to_string().contains(expected), "{error}");
    assert_eq!(node.read_active().unwrap(), before);
}
fn step(state: &State, c: &Config, height: u64, transactions: &[Vec<u8>]) -> State {
    pon_executor::execute(
        state,
        transactions,
        height,
        development_public(3).unwrap(),
        [4; 32],
        4,
        c,
    )
    .unwrap()
    .state
}
fn attestation(
    c: &Config,
    state: &State,
    cid: Hash,
    who: u64,
    account_sequence: u64,
    tag: u8,
    claimed: (u64, Hash),
) -> Vec<u8> {
    let round = evaluation::round(&object(state, cid)["public_evaluation"]).unwrap();
    let salt = [who as u8 + 1; 32];
    let (score, evidence) = claimed;
    let mut payload = cid.to_vec();
    payload.extend(round);
    if tag == 14 {
        payload.extend(
            evaluation::reveal_commitment_for(
                &object(state, cid)["public_evaluation"],
                &evaluation::Reveal {
                    round,
                    candidate: cid,
                    evaluator: development_public(who).unwrap(),
                    plan: c.plan,
                    evidence,
                    score,
                    salt,
                },
            )
            .unwrap(),
        );
    } else {
        assert_eq!(tag, 15);
        payload.extend(c.plan);
        payload.extend(evidence);
        payload.extend(score.to_le_bytes());
        payload.extend(salt);
    }
    signed(c, who, account_sequence, tag, payload)
}
fn attestations(c: &Config, state: &State, candidates: &[Hash], tag: u8) -> Vec<Vec<u8>> {
    let mut transactions = Vec::new();
    for who in 0..3 {
        let mut nonce = next_nonce(state, who);
        for &cid in candidates {
            if object(state, cid)["owner"] == hex::encode(development_public(who).unwrap()) {
                continue;
            }
            let evidence = model_evidence::evidence(state, cid).unwrap();
            transactions.push(attestation(
                c,
                state,
                cid,
                who,
                nonce,
                tag,
                (
                    evidence["score"].as_u64().unwrap(),
                    read_hash(&evidence["digest"]),
                ),
            ));
            nonce += 1;
        }
    }
    transactions
}
fn leaf(cid: Hash, who: u64, score: u64) -> Hash {
    hash(
        b"allocation-leaf",
        &[
            &cid,
            &development_public(who).unwrap(),
            &score.to_le_bytes(),
        ],
    )
}
fn pair(a: Hash, b: Hash) -> Hash {
    if a < b {
        hash(b"allocation-node", &[&a, &b])
    } else {
        hash(b"allocation-node", &[&b, &a])
    }
}
fn release(
    c: &Config,
    state: &State,
    bundle: &FactorWitnessV2,
    budget: u64,
    root: Hash,
    allocations: &[(Hash, u64)],
) -> (Hash, Vec<u8>) {
    let total: u64 = allocations.iter().map(|(_, score)| score).sum();
    let id = hash(
        b"release",
        &[
            &bundle.parent_ref,
            &bundle.contribution_id,
            &budget.to_le_bytes(),
            &root,
            &total.to_le_bytes(),
        ],
    );
    let mut payload = id.to_vec();
    payload.extend(bundle.parent_ref);
    payload.extend(bundle.contribution_id);
    payload.extend(budget.to_le_bytes());
    payload.extend(root);
    payload.extend(total.to_le_bytes());
    payload.push(u8::try_from(allocations.len()).unwrap());
    for (cid, score) in allocations {
        payload.extend(cid);
        payload.extend(score.to_le_bytes());
    }
    (id, signed(c, 3, next_nonce(state, 3), 8, payload))
}
fn claim(c: &Config, state: &State, release: Hash, cid: Hash, who: u64, sibling: Hash) -> Vec<u8> {
    let mut payload = release.to_vec();
    payload.extend(cid);
    payload.extend(POSITIVE_SCORE.to_le_bytes());
    payload.push(1);
    payload.extend(sibling);
    signed(c, who, next_nonce(state, who), 9, payload)
}
fn appeal(c: &Config, state: &State, cid: Hash, who: u64) -> Vec<u8> {
    let evaluation = evaluation::read_evaluation(state, cid).unwrap();
    let mut payload = cid.to_vec();
    payload.extend(evaluation::closed_digest(&evaluation).unwrap());
    payload.extend([1; 32]);
    payload.extend([2; 32]);
    signed(c, who, next_nonce(state, who), 17, payload)
}
fn quorum_attestations(c: &Config, state: &State, candidates: &[Hash], tag: u8) -> Vec<Vec<u8>> {
    let mut transactions = Vec::new();
    for who in [0, 2, 3] {
        let mut nonce = next_nonce(state, who);
        for &cid in candidates {
            if object(state, cid)["owner"] == hex::encode(development_public(who).unwrap()) {
                continue;
            }
            let evidence = model_evidence::evidence(state, cid).unwrap();
            transactions.push(attestation(
                c,
                state,
                cid,
                who,
                nonce,
                tag,
                (
                    evidence["score"].as_u64().unwrap(),
                    read_hash(&evidence["digest"]),
                ),
            ));
            nonce += 1;
        }
    }
    transactions
}
fn quorum_conflict(c: &Config, state: &State, cid: Hash, offender: u64, submitter: u64) -> Vec<u8> {
    let e = evaluation::read_evaluation(state, cid).unwrap();
    let mut prefix = cid.to_vec();
    prefix.extend(evaluation::round(&e).unwrap());
    let mut payload = cid.to_vec();
    for value in [41, 42] {
        let mut disputed = prefix.clone();
        disputed.extend([value; 32]);
        let raw = signed(c, offender, u64::from(value), 14, disputed);
        payload.extend(u16::try_from(raw.len()).unwrap().to_le_bytes());
        payload.extend(raw);
    }
    signed(c, submitter, next_nonce(state, submitter), 16, payload)
}

#[test]
fn explicit_quorum_native_release_survives_one_absence_and_hash_appeal_with_durable_reorg() {
    let directory = tempfile::tempdir().unwrap();
    let c = Config::installed_with_model_profiles(
        evaluation::QUORUM_PROFILE,
        "legacy-task-v1",
        model_evidence::PROFILE,
    )
    .unwrap();
    let selected = Settings::development_with_model_profiles(
        None,
        evaluation::QUORUM_PROFILE,
        "legacy-task-v1",
        model_evidence::PROFILE,
    )
    .unwrap();
    let mut node = Node::open(directory.path(), selected.clone(), 4).unwrap();
    let initial = node.read_active().unwrap().2;
    let component = build(&initial, &c, 0, memorizing_factors(1), [8; 32]);
    let root = leaf(component.contribution_id, 0, POSITIVE_SCORE);
    let bundle = build(&initial, &c, 3, memorizing_factors(2), root);
    let bundle_transaction = signed(&c, 3, 1, 23, bundle.encode().unwrap());
    let candidates = [component.contribution_id, bundle.contribution_id];
    let allocations = [(component.contribution_id, POSITIVE_SCORE)];
    let mut tip = selected.genesis();
    let mut closed_tip = tip;
    let mut closed = Value::Null;
    let mut release_id = [0; 32];
    for height in 1..=56 {
        let state = node.read_active().unwrap().2;
        let transactions = match height {
            1 => vec![
                signed(&c, 0, 1, 23, component.encode().unwrap()),
                bundle_transaction.clone(),
            ],
            16 => {
                let record = model_evidence::evidence(&state, bundle.contribution_id).unwrap();
                false_attestation_refused(
                    &c,
                    &state,
                    bundle.contribution_id,
                    (POSITIVE_SCORE + 1, read_hash(&record["digest"])),
                );
                quorum_attestations(&c, &state, &candidates, 14)
            }
            32 => quorum_attestations(&c, &state, &candidates, 15),
            49 => vec![appeal(&c, &state, bundle.contribution_id, 3)],
            50 => vec![quorum_conflict(&c, &state, bundle.contribution_id, 1, 3)],
            56 => {
                let (_, valid_release) = release(&c, &state, &bundle, 1000, root, &allocations);
                // Same block, distinct senders: global conflict before release
                // must invalidate speculative adoption even with four workers.
                let conflicting = quorum_conflict(&c, &state, bundle.contribution_id, 2, 0);
                assert_eq!(
                    pon_executor::execute(
                        &state,
                        &[conflicting, valid_release.clone()],
                        height,
                        development_public(3).unwrap(),
                        [4; 32],
                        4,
                        &c
                    )
                    .err(),
                    Some("PUBLIC_EVAL_ADOPTION")
                );
                let (id, _) = release(&c, &state, &bundle, 1000, root, &allocations);
                release_id = id;
                vec![valid_release]
            }
            _ => vec![],
        };
        tip = append(&mut node, tip, height, transactions, "quorum-v2");
        if height == 48 {
            closed_tip = tip;
            for cid in candidates {
                let e = evaluation::read_evaluation(&node.read_active().unwrap().2, cid).unwrap();
                assert_eq!(e["closed"]["status"], "complete-scored");
                assert_eq!(e["closed"]["score"], POSITIVE_SCORE);
                assert_eq!(e["closed"]["quorum"], 2);
                assert_eq!(e["closed"]["matching_reveal_count"], 2);
                assert_eq!(e["closed"]["missing_reveal_count"], 1);
                assert_eq!(e["reveals"].as_object().unwrap().len(), 2);
            }
            closed =
                evaluation::read_evaluation(&node.read_active().unwrap().2, bundle.contribution_id)
                    .unwrap()["closed"]
                    .clone();
        }
    }
    let adopted = node.read_active().unwrap().2;
    assert_eq!(adopted["model:current"], hex::encode(release_id));
    let e = evaluation::read_evaluation(&adopted, bundle.contribution_id).unwrap();
    assert_eq!(e["closed"], closed);
    assert_eq!(e["appeals"].as_object().unwrap().len(), 1);
    assert_eq!(e["conflicts"].as_object().unwrap().len(), 1);
    let observation = node
        .evaluation_observation(bundle.contribution_id, CLOCK, 128)
        .unwrap();
    let round_observation = node
        .evaluation_round_observation(bundle.contribution_id, CLOCK, 128)
        .unwrap();
    assert_eq!(observation.closed_result(), Some(&closed));
    assert_eq!(round_observation.closed_result(), Some(&closed));
    for anchor in [
        serde_json::to_value(observation.candidate_anchor()).unwrap(),
        serde_json::to_value(round_observation.candidate_anchor()).unwrap(),
    ] {
        assert_eq!(
            anchor["transaction"],
            hex::encode(hash(b"tx-id", &[&bundle_transaction]))
        );
        assert_eq!(anchor["transaction_membership_verified"], true);
        assert_eq!(anchor["height"], 1);
    }
    drop(node);
    assert!(Node::open(directory.path(), settings(), 1).is_err());
    let mut node = Node::open(directory.path(), selected.clone(), 2).unwrap();
    assert_eq!(node.read_active().unwrap().2, adopted);
    node.check_evaluation_observation(&observation, CLOCK, 128)
        .unwrap();
    node.check_evaluation_round_observation(&round_observation, CLOCK, 128)
        .unwrap();

    // Exact native executor transitions exercise the next round, not sparse
    // PNW1 headers. A saturated public corpus remains zero gain after adoption.
    let next = factor::build_witness(
        &adopted,
        &c,
        development_public(0).unwrap(),
        1,
        factor::FactorInputV2 {
            slot: 0,
            rank: 2,
            coefficients: memorizing_factors(3),
        },
        [8; 32],
    )
    .unwrap();
    let next_state = step(
        &adopted,
        &c,
        129,
        &[signed(
            &c,
            0,
            next_nonce(&adopted, 0),
            23,
            next.encode().unwrap(),
        )],
    );
    let next_eval = &object(&next_state, next.contribution_id)["public_evaluation"];
    assert_eq!(next_eval["plan"]["parent"], hex::encode(release_id));
    assert_eq!(next_eval["plan"]["generation"], 1);
    assert_eq!(next_eval["plan"]["quorum"], 2);
    assert_eq!(next_eval["plan"]["roster"].as_array().unwrap().len(), 3);
    assert_eq!(
        next_eval["plan"]["disqualified_at_freeze"],
        json!([hex::encode(development_public(1).unwrap())])
    );
    assert_ne!(
        next_eval["plan"]["generation_context"],
        e["plan"]["generation_context"]
    );
    assert_eq!(
        model_evidence::evidence(&next_state, next.contribution_id).unwrap()["score"],
        0
    );
    let mut stale = next.contribution_id.to_vec();
    stale.extend(evaluation::round(&e).unwrap());
    stale.extend([9; 32]);
    assert_eq!(
        pon_executor::execute(
            &next_state,
            &[signed(&c, 2, next_nonce(&next_state, 2), 14, stale)],
            144,
            development_public(3).unwrap(),
            [4; 32],
            4,
            &c
        )
        .err(),
        Some("PUBLIC_EVAL_ROUND")
    );

    // A heavier actual branch removes the old adoption and its local branch
    // records. It does not rewrite the shared historical closure or invent finality.
    let mut fork = closed_tip;
    for height in 49..=57 {
        fork = append(&mut node, fork, height, vec![], "quorum-v2-reorg");
    }
    let rolled_back = node.read_active().unwrap().2;
    assert_eq!(node.active().unwrap().0, fork);
    assert_eq!(rolled_back["model:current"], initial["model:current"]);
    assert!(!rolled_back.contains_key(&format!("release:{}", hex::encode(release_id))));
    assert!(!rolled_back.contains_key(&format!(
        "evaluation-disqualified:{}",
        hex::encode(development_public(1).unwrap())
    )));
    assert_eq!(
        evaluation::read_evaluation(&rolled_back, bundle.contribution_id).unwrap()["closed"],
        closed
    );
    assert_eq!(
        node.check_evaluation_observation(&observation, CLOCK, 128)
            .unwrap_err()
            .to_string(),
        "STALE_VIEW"
    );
    assert_eq!(
        node.check_evaluation_round_observation(&round_observation, CLOCK, 128)
            .unwrap_err()
            .to_string(),
        "STALE_VIEW"
    );
    assert_eq!(
        node.evaluation_observation(bundle.contribution_id, CLOCK, 128)
            .unwrap()
            .closed_result(),
        Some(&closed)
    );
    assert_eq!(
        node.evaluation_round_observation(bundle.contribution_id, CLOCK, 128)
            .unwrap()
            .closed_result(),
        Some(&closed)
    );
    drop(node);
    assert_eq!(
        Node::open(directory.path(), selected, 1)
            .unwrap()
            .read_active()
            .unwrap()
            .2,
        rolled_back
    );
}
fn false_attestation_refused(c: &Config, state: &State, cid: Hash, claimed: (u64, Hash)) {
    // This is direct native executor branching from an actual admitted packet.
    // The forged reveal matches its own signed commitment, so commitment checking
    // alone cannot reject it: the empirical evidence binding must do so.
    let committed = step(
        state,
        c,
        16,
        &[attestation(
            c,
            state,
            cid,
            0,
            next_nonce(state, 0),
            14,
            claimed,
        )],
    );
    let transaction = attestation(
        c,
        &committed,
        cid,
        0,
        next_nonce(&committed, 0),
        15,
        claimed,
    );
    assert_eq!(
        pon_executor::execute(
            &committed,
            &[transaction],
            32,
            development_public(3).unwrap(),
            [4; 32],
            4,
            c,
        )
        .err(),
        Some("MODEL_EVIDENCE_REVEAL")
    );
}

#[test]
fn objective_release_shared_source_reward_reopen_and_review_fork_are_native() {
    let directory = tempfile::tempdir().unwrap();
    let c = cfg();
    let settings = settings();
    record_context(&c, "reward");
    record_context(&c, "review-fork");
    let mut node = Node::open(directory.path(), settings.clone(), 4).unwrap();
    let initial = node.read_active().unwrap().2;
    let first = build(&initial, &c, 0, memorizing_factors(1), [8; 32]);
    let second = build(&initial, &c, 1, memorizing_factors(2), [8; 32]);
    let leaves = [
        leaf(first.contribution_id, 0, POSITIVE_SCORE),
        leaf(second.contribution_id, 1, POSITIVE_SCORE),
    ];
    let root = pair(leaves[0], leaves[1]);
    let bundle = build(&initial, &c, 3, memorizing_factors(3), root);
    let candidates = [
        first.contribution_id,
        second.contribution_id,
        bundle.contribution_id,
    ];
    let allocations = [
        (first.contribution_id, POSITIVE_SCORE),
        (second.contribution_id, POSITIVE_SCORE),
    ];
    let mut tip = node.settings().genesis();
    let mut branch_parent = tip;
    let mut released = [0; 32];
    let mut source_key = String::new();
    let mut original_evidence = Value::Null;
    for height in 1..=76 {
        let state = node.read_active().unwrap().2;
        let transactions = match height {
            1 => vec![
                signed(&c, 0, 1, 23, first.encode().unwrap()),
                signed(&c, 1, 1, 23, second.encode().unwrap()),
                signed(&c, 3, 1, 23, bundle.encode().unwrap()),
            ],
            16 => {
                let evidence = model_evidence::evidence(&state, bundle.contribution_id).unwrap();
                let digest = read_hash(&evidence["digest"]);
                false_attestation_refused(
                    &c,
                    &state,
                    bundle.contribution_id,
                    (POSITIVE_SCORE + 1, digest),
                );
                let mut wrong = digest;
                wrong[0] ^= 1;
                false_attestation_refused(
                    &c,
                    &state,
                    bundle.contribution_id,
                    (POSITIVE_SCORE, wrong),
                );
                attestations(&c, &state, &candidates, 14)
            }
            32 => attestations(&c, &state, &candidates, 15),
            56 => {
                // Both payees are known aliases. Each individual share is below
                // the cap, but their combined 100002-unit reservation must fail.
                refusal(
                    &node,
                    tip,
                    height,
                    release(&c, &state, &bundle, 100_002, root, &allocations).1,
                    "MODEL_EVIDENCE_SOURCE_BUDGET",
                );
                let wrong = [(first.contribution_id, POSITIVE_SCORE + 1), allocations[1]];
                refusal(
                    &node,
                    tip,
                    height,
                    release(&c, &state, &bundle, 100_000, root, &wrong).1,
                    "EVIDENCE",
                );
                let mut wrong_root = root;
                wrong_root[0] ^= 1;
                refusal(
                    &node,
                    tip,
                    height,
                    release(&c, &state, &bundle, 100_000, wrong_root, &allocations).1,
                    "ROOT",
                );
                let (id, transaction) = release(&c, &state, &bundle, 100_000, root, &allocations);
                released = id;
                vec![transaction]
            }
            58 => vec![appeal(&c, &state, bundle.contribution_id, 3)],
            75 => {
                refusal(
                    &node,
                    tip,
                    height,
                    claim(&c, &state, released, first.contribution_id, 0, leaves[1]),
                    "STATE",
                );
                vec![]
            }
            76 => vec![
                claim(&c, &state, released, first.contribution_id, 0, leaves[1]),
                claim(&c, &state, released, second.contribution_id, 1, leaves[0]),
            ],
            _ => vec![],
        };
        tip = append(&mut node, tip, height, transactions, "reward");
        let after = node.read_active().unwrap().2;
        if height == 1 {
            for cid in candidates {
                let evidence = model_evidence::evidence(&after, cid).unwrap();
                assert_eq!(evidence["candidate_correct"], 25);
                assert_eq!(evidence["strongest_correct"], 19);
                assert_eq!(evidence["rows"], 25);
                assert_eq!(evidence["score"], POSITIVE_SCORE);
                assert_eq!(evidence["controls"].as_array().unwrap().len(), 4);
                for acceptance in [
                    "prospective_accepted",
                    "independent_accepted",
                    "public_reward_eligible",
                ] {
                    assert_eq!(evidence[acceptance], false);
                }
                assert_eq!(object(&after, cid)["score"], 0);
                assert_eq!(
                    object(&after, cid)["model_evidence_v3"]["digest"],
                    evidence["digest"]
                );
            }
            let a = &object(&after, first.contribution_id)["model_evidence_v3"];
            let b = &object(&after, second.contribution_id)["model_evidence_v3"];
            assert_eq!(a["source"], b["source"]);
            assert_eq!(a["root_work"], b["root_work"]);
            source_key = model_evidence::source_key(0, read_hash(&a["source"]));
            assert_eq!(after[&source_key]["intakes"], 2);
            assert_eq!(after[&source_key]["reserved_units"], 0);
            original_evidence = model_evidence::evidence(&after, bundle.contribution_id).unwrap();
        }
        if height == 48 {
            branch_parent = tip;
            for cid in candidates {
                assert_eq!(object(&after, cid)["status"], "evaluated");
                assert_eq!(object(&after, cid)["score"], POSITIVE_SCORE);
            }
        }
        if height == 56 {
            assert_eq!(after["model:current"], hex::encode(released));
            assert_eq!(after[&source_key]["reserved_units"], 100_000);
            let request = NativeBudgetRequestV1 {
                operation: hash(b"native-budget-contribution-test", &[&released]),
                subject: first.contribution_id,
                beneficiary: development_public(0).unwrap(),
                lane: NativeBudgetLaneV1::Contribution,
                source: released,
                amount: 50_000,
                source_cap: 100_000,
                resource_cap: [100, 100],
                resource_reservation: [20, 20],
                contribution: Some(NativeContributionClaimV1 {
                    candidate: first.contribution_id,
                    score: POSITIVE_SCORE,
                    siblings: vec![leaves[1]],
                }),
            };
            let mut wrong = request.clone();
            wrong.operation = hash(b"native-budget-wrong-payee-test", &[&released]);
            wrong.beneficiary = development_public(1).unwrap();
            assert_eq!(
                node.reserve_native_budget_v1(wrong)
                    .err()
                    .unwrap()
                    .to_string(),
                "BUDGET_ALLOCATION"
            );
            let observation = node.reserve_native_budget_v1(request.clone()).unwrap();
            assert!(
                !observation.funding_current
                    && !observation.chain_funds_locked
                    && !observation.payment_executed
                    && !observation.execution_authority
            );
            node.settle_native_budget_resources_v1(request.operation, [10, 10])
                .unwrap();
        }
        if height == 58 {
            assert!(!after.contains_key(&format!(
                "contribution:{}",
                hex::encode(bundle.contribution_id)
            )));
            let evaluation = evaluation::read_evaluation(&after, bundle.contribution_id).unwrap();
            assert_eq!(evaluation["closed"]["score"], POSITIVE_SCORE);
            assert_eq!(evaluation["appeals"].as_object().unwrap().len(), 1);
            assert_eq!(after["model:current"], hex::encode(released));
        }
    }
    let paid = node.read_active().unwrap().2;
    let release_key = format!("release:{}", hex::encode(released));
    assert_eq!(paid[&release_key]["remaining"], 0);
    for cid in [first.contribution_id, second.contribution_id] {
        assert_eq!(paid[&release_key]["claims"][hex::encode(cid)], 50_000);
    }
    assert_eq!(paid[&source_key]["reserved_units"], 100_000);
    assert_eq!(
        model_evidence::evidence(&paid, bundle.contribution_id).unwrap(),
        original_evidence
    );
    refusal(
        &node,
        tip,
        77,
        claim(&c, &paid, released, first.contribution_id, 0, leaves[1]),
        "DUPLICATE",
    );
    drop(node);
    let mut node = Node::open(directory.path(), settings.clone(), 2).unwrap();
    assert_eq!(node.read_active().unwrap().2, paid);
    assert_eq!(
        model_evidence::evidence(&node.read_active().unwrap().2, bundle.contribution_id).unwrap(),
        original_evidence
    );

    // A genuine branch from the completed evaluation gains more cumulative work.
    // Its timely participant objection prevents adoption throughout the round,
    // and switching to it removes the old release, claims and source reservation.
    let mut fork = branch_parent;
    for height in 49..=77 {
        let state = node.state_at(fork).unwrap();
        let transactions = if height == 49 {
            vec![appeal(&c, &state, bundle.contribution_id, 0)]
        } else {
            vec![]
        };
        if height == 56 || height == 65 {
            refusal(
                &node,
                fork,
                height,
                release(&c, &state, &bundle, 100_000, root, &allocations).1,
                "MODEL_EVIDENCE_REVIEW_HOLD",
            );
        }
        fork = append(&mut node, fork, height, transactions, "review-fork");
    }
    assert_eq!(node.active().unwrap().0, fork);
    let rolled_back = node.read_active().unwrap().2;
    assert_eq!(rolled_back["model:current"], hex::encode(bundle.parent_ref));
    assert!(!rolled_back.contains_key(&release_key));
    assert_eq!(rolled_back[&source_key]["reserved_units"], 0);
    assert_eq!(rolled_back[&source_key]["intakes"], 2);
    assert_eq!(
        object(&rolled_back, bundle.contribution_id)["status"],
        "expired"
    );
    assert_eq!(object(&rolled_back, bundle.contribution_id)["score"], 0);
    assert_eq!(
        evaluation::read_evaluation(&rolled_back, bundle.contribution_id).unwrap()["closed"]
            ["score"],
        POSITIVE_SCORE
    );
    refusal(
        &node,
        fork,
        78,
        release(&c, &rolled_back, &bundle, 100_000, root, &allocations).1,
        "EVIDENCE",
    );
    drop(node);
    let node = Node::open(directory.path(), settings, 1).unwrap();
    assert_eq!(node.read_active().unwrap().2, rolled_back);
    // Exercise mandatory native expiry without claiming a sparse-height header.
    let expired = step(&rolled_back, &c, 128, &[]);
    assert!(!expired.contains_key(&format!(
        "contribution:{}",
        hex::encode(bundle.contribution_id)
    )));
    assert!(!expired.contains_key(&source_key));
    let next = factor::build_witness(
        &expired,
        &c,
        development_public(0).unwrap(),
        1,
        factor::FactorInputV2 {
            slot: 0,
            rank: 2,
            coefficients: memorizing_factors(1),
        },
        [8; 32],
    )
    .unwrap();
    let new_round = step(
        &expired,
        &c,
        129,
        &[signed(
            &c,
            0,
            next_nonce(&expired, 0),
            23,
            next.encode().unwrap(),
        )],
    );
    let next_source =
        read_hash(&object(&new_round, next.contribution_id)["model_evidence_v3"]["source"]);
    assert_eq!(
        new_round[&model_evidence::source_key(1, next_source)]["intakes"],
        1
    );
    assert_eq!(
        new_round[&model_evidence::source_key(1, next_source)]["reserved_units"],
        0
    );
    // The old archive is retained for 256 blocks after its actual closure at48.
    let pruned = step(&expired, &c, 305, &[]);
    for cid in candidates {
        assert!(model_evidence::evidence(&pruned, cid).is_err());
        assert!(!pruned.contains_key(&format!("evaluation-archive:{}", hex::encode(cid))));
        assert!(!pruned
            .keys()
            .any(|key| key.starts_with(&evaluation::record_prefix(cid))));
    }
}

#[test]
fn zero_gain_and_noop_cannot_become_positive_by_consistent_signatures() {
    let directory = tempfile::tempdir().unwrap();
    let c = cfg();
    let mut node = Node::open(directory.path(), settings(), 2).unwrap();
    let initial = node.read_active().unwrap().2;
    let mut coefficients = vec![0; 260];
    coefficients[0] = 1;
    coefficients[3] = 1;
    let candidate = build(&initial, &c, 3, coefficients, [8; 32]);
    let genesis = node.settings().genesis();
    let mut noop = candidate.clone();
    noop.factors.fill(0);
    refusal(
        &node,
        genesis,
        1,
        signed(&c, 3, 1, 23, noop.encode().unwrap()),
        "FACTOR_NOOP",
    );
    append(
        &mut node,
        genesis,
        1,
        vec![signed(&c, 3, 1, 23, candidate.encode().unwrap())],
        "zero-gain",
    );
    let admitted = node.read_active().unwrap().2;
    let evidence = model_evidence::evidence(&admitted, candidate.contribution_id).unwrap();
    assert_eq!(evidence["score"], 0);
    assert!(
        evidence["candidate_correct"].as_u64().unwrap()
            <= evidence["strongest_correct"].as_u64().unwrap()
    );
    false_attestation_refused(
        &c,
        &admitted,
        candidate.contribution_id,
        (1, read_hash(&evidence["digest"])),
    );
    let committed = step(
        &admitted,
        &c,
        16,
        &attestations(&c, &admitted, &[candidate.contribution_id], 14),
    );
    let revealed = step(
        &committed,
        &c,
        32,
        &attestations(&c, &committed, &[candidate.contribution_id], 15),
    );
    let closed = step(&revealed, &c, 48, &[]);
    assert_eq!(object(&closed, candidate.contribution_id)["score"], 0);
    assert!(evaluation::adoption_allowed(
        &evaluation::read_evaluation(&closed, candidate.contribution_id).unwrap(),
        56,
    )
    .is_err());
    let transaction = release(
        &c,
        &closed,
        &candidate,
        100_000,
        candidate.components_root,
        &[(candidate.contribution_id, 1)],
    )
    .1;
    assert!(matches!(
        pon_executor::execute(
            &closed,
            &[transaction],
            56,
            development_public(3).unwrap(),
            [4; 32],
            4,
            &c,
        )
        .err(),
        Some("PUBLIC_EVAL_ADOPTION" | "MODEL_EVIDENCE_GAIN" | "EVIDENCE")
    ));
    assert_eq!(closed["model:current"], initial["model:current"]);
    assert!(!closed.keys().any(|key| key.starts_with("release:")));
}

#[test]
fn known_alias_intakes_share_one_limit_and_reorganization_restores_it() {
    let directory = tempfile::tempdir().unwrap();
    let c = cfg();
    record_context(&c, "source-intakes");
    record_context(&c, "intake-fork");
    let settings = settings();
    let mut node = Node::open(directory.path(), settings.clone(), 2).unwrap();
    let initial = node.read_active().unwrap().2;
    let genesis = node.settings().genesis();
    let mut tip = genesis;
    let mut first = None;
    let mut source_key = String::new();
    for height in 1..=4 {
        let who = (height - 1) % 2;
        let state = node.read_active().unwrap().2;
        let witness = build(&state, &c, who, memorizing_factors(height as i16), [8; 32]);
        tip = append(
            &mut node,
            tip,
            height,
            vec![signed(
                &c,
                who,
                next_nonce(&state, who),
                23,
                witness.encode().unwrap(),
            )],
            "source-intakes",
        );
        let state = node.read_active().unwrap().2;
        let source =
            read_hash(&object(&state, witness.contribution_id)["model_evidence_v3"]["source"]);
        if height == 1 {
            source_key = model_evidence::source_key(0, source);
            first = Some(witness);
        }
        assert_eq!(source_key, model_evidence::source_key(0, source));
        assert_eq!(state[&source_key]["intakes"], height);
    }
    let capped = node.read_active().unwrap().2;
    for who in 0..2 {
        let fifth = build(&capped, &c, who, memorizing_factors(5), [9; 32]);
        refusal(
            &node,
            tip,
            5,
            signed(
                &c,
                who,
                next_nonce(&capped, who),
                23,
                fifth.encode().unwrap(),
            ),
            "MODEL_EVIDENCE_SOURCE_LIMIT",
        );
    }
    // Another installed source has its own bounded allowance.
    let separate = build(&capped, &c, 2, memorizing_factors(5), [9; 32]);
    append(
        &mut node,
        tip,
        5,
        vec![signed(&c, 2, 1, 23, separate.encode().unwrap())],
        "source-intakes",
    );
    assert_eq!(node.read_active().unwrap().2[&source_key]["intakes"], 4);
    let mut fork = genesis;
    for height in 1..=6 {
        fork = append(&mut node, fork, height, vec![], "intake-fork");
    }
    assert_eq!(node.active().unwrap().0, fork);
    let rolled_back = node.read_active().unwrap().2;
    assert!(!rolled_back
        .keys()
        .any(|key| key.starts_with("model-source-v3:")));
    assert!(!rolled_back
        .keys()
        .any(|key| key.starts_with("model-evidence-v3:")));
    assert_eq!(rolled_back["model:current"], initial["model:current"]);
    let first = first.unwrap();
    append(
        &mut node,
        fork,
        7,
        vec![signed(&c, 0, 1, 23, first.encode().unwrap())],
        "intake-fork",
    );
    let restored = node.read_active().unwrap().2;
    assert_eq!(restored[&source_key]["intakes"], 1);
    assert!(model_evidence::evidence(&restored, first.contribution_id).is_ok());
    drop(node);
    assert_eq!(
        Node::open(directory.path(), settings, 1)
            .unwrap()
            .read_active()
            .unwrap()
            .2,
        restored
    );
    assert!(Node::open(directory.path(), Settings::development(None).unwrap(), 1).is_err());
}

#[test]
fn missing_corrupt_or_noncanonical_control_bytes_refuse_signed_admission() {
    let directory = tempfile::tempdir().unwrap();
    let c = cfg();
    let node = Node::open(directory.path(), settings(), 2).unwrap();
    let initial = node.read_active().unwrap().2;
    let witness = build(&initial, &c, 3, memorizing_factors(1), [8; 32]);
    let transaction = signed(&c, 3, 1, 23, witness.encode().unwrap());
    let genesis_prefix = format!(
        "linear-model-v2:{}:",
        initial["model:current"].as_str().unwrap()
    );
    let control_metadata = initial
        .keys()
        .find(|key| {
            key.starts_with("linear-model-v2:")
                && key.ends_with(":meta")
                && !key.starts_with(&genesis_prefix)
        })
        .unwrap();
    let control_chunk = format!("{}00", control_metadata.strip_suffix("meta").unwrap());
    for variation in 0..3 {
        // These isolated executor inputs exercise full control loading. They do
        // not represent a writable native-store corruption or a valid block root.
        let mut damaged = initial.clone();
        match variation {
            0 => {
                damaged.remove(&control_chunk);
            }
            1 => {
                let mut raw = hex::decode(damaged[&control_chunk].as_str().unwrap()).unwrap();
                *raw.last_mut().unwrap() ^= 1;
                damaged.insert(control_chunk.clone(), json!(hex::encode(raw)));
            }
            _ => {
                damaged.get_mut(control_metadata).unwrap()["unexpected"] = json!(true);
            }
        }
        let error = pon_executor::execute(
            &damaged,
            std::slice::from_ref(&transaction),
            1,
            development_public(3).unwrap(),
            [4; 32],
            4,
            &c,
        )
        .err()
        .unwrap();
        assert!(error.starts_with("FACTOR_MODEL_"), "{error}");
        assert!(!damaged.contains_key(&format!(
            "contribution:{}",
            hex::encode(witness.contribution_id)
        )));
    }
    assert_eq!(node.read_active().unwrap().2, initial);
}

#[test]
fn combined_continuity_and_model_evidence_complete_native_lifecycle_and_cleanup() {
    let directory = tempfile::tempdir().unwrap();
    let c = Config::installed_with_model_profiles(
        evaluation::PROFILE,
        continuity_v1::PROFILE,
        model_evidence::PROFILE,
    )
    .unwrap();
    let combined_settings = Settings::development_with_model_profiles(
        None,
        evaluation::PROFILE,
        continuity_v1::PROFILE,
        model_evidence::PROFILE,
    )
    .unwrap();
    let task_only =
        Settings::development_with_profiles(None, evaluation::PROFILE, continuity_v1::PROFILE)
            .unwrap();
    let model_only = settings();
    assert_eq!(c.params["consensus_revision"], 13);
    assert!(continuity_v1::enabled(&c));
    assert!(model_evidence::enabled(&c));
    assert_eq!(c.network, combined_settings.network());
    assert_eq!(c.parameters, combined_settings.parameters());
    for standalone in [&task_only, &model_only] {
        assert_ne!(combined_settings.network(), standalone.network());
        assert_ne!(combined_settings.parameters(), standalone.parameters());
        assert_ne!(combined_settings.genesis(), standalone.genesis());
    }
    record_context(&c, "combined-continuity");
    eprintln!(
        "combined context: network={}, parameters={}, genesis={}",
        hex::encode(c.network),
        hex::encode(c.parameters),
        hex::encode(combined_settings.genesis())
    );

    let mut node = Node::open(directory.path(), combined_settings.clone(), 4).unwrap();
    let initial = node.read_active().unwrap().2;
    continuity_v1::check_state(&initial, 0, &c).unwrap();
    let initial_capacity = continuity_v1::capacity(&initial, 0, &c).unwrap();
    assert_eq!(initial_capacity.archive_reserve, 0);
    assert_eq!(initial_capacity.reward_queue_reserve, 20);
    assert_eq!(initial_capacity.credit_account_reserve, 0);
    assert_eq!(
        node.make(
            combined_settings.genesis(),
            vec![],
            development_public(3).unwrap(),
            combined_settings.genesis_time() + 10,
            4096,
        )
        .unwrap_err()
        .to_string(),
        "EXPLICIT_TASK_REQUIRED"
    );

    let first = build(&initial, &c, 0, memorizing_factors(1), [8; 32]);
    let second = build(&initial, &c, 1, memorizing_factors(2), [8; 32]);
    let leaves = [
        leaf(first.contribution_id, 0, POSITIVE_SCORE),
        leaf(second.contribution_id, 1, POSITIVE_SCORE),
    ];
    let root = pair(leaves[0], leaves[1]);
    let bundle = build(&initial, &c, 3, memorizing_factors(3), root);
    let candidates = [
        first.contribution_id,
        second.contribution_id,
        bundle.contribution_id,
    ];
    let allocations = [
        (first.contribution_id, POSITIVE_SCORE),
        (second.contribution_id, POSITIVE_SCORE),
    ];
    let component_prefixes = [first.candidate_artifact, second.candidate_artifact]
        .map(|id| format!("linear-model-v2:{}:", hex::encode(id)));
    let current_model_prefix = format!(
        "linear-model-v2:{}:",
        hex::encode(bundle.candidate_artifact)
    );
    let installed_model_keys: Vec<_> = initial
        .keys()
        .filter(|key| key.starts_with("linear-model-v2:"))
        .cloned()
        .collect();
    let mut released = [0; 32];
    let mut source_key = String::new();
    let mut native_packets = 0;
    let mut peak_required_keys = initial_capacity.required_keys;
    for height in 1..=306 {
        let (parent, _, state) = node.read_active().unwrap();
        assert_eq!(node.parent_height(parent).unwrap() + 1, height);
        let previous_capacity = continuity_v1::capacity(&state, height - 1, &c).unwrap();
        continuity_v1::check_state(&state, height - 1, &c).unwrap();
        let transactions = match height {
            1 => vec![
                signed(&c, 0, 1, 23, first.encode().unwrap()),
                signed(&c, 1, 1, 23, second.encode().unwrap()),
                signed(&c, 3, 1, 23, bundle.encode().unwrap()),
            ],
            16 => attestations(&c, &state, &candidates, 14),
            32 => attestations(&c, &state, &candidates, 15),
            56 => {
                let (id, transaction) = release(&c, &state, &bundle, 100_000, root, &allocations);
                released = id;
                vec![transaction]
            }
            76 => vec![
                claim(&c, &state, released, first.contribution_id, 0, leaves[1]),
                claim(&c, &state, released, second.contribution_id, 1, leaves[0]),
            ],
            _ => vec![],
        };
        // Every height uses the explicit installed maintenance relation. This
        // chain does not manufacture full-capacity or useful-task-work evidence.
        let maintenance_only = transactions.is_empty();
        let packet = node
            .make_consensus_maintenance(
                parent,
                transactions,
                development_public(3).unwrap(),
                combined_settings.genesis_time() + height * 10,
                4096,
            )
            .unwrap();
        assert_eq!(packet.header.height, height);
        assert_eq!(
            packet.header.work_task,
            continuity_v1::maintenance_task().unwrap()
        );
        let id = node.admit(&packet, CLOCK).unwrap();
        assert_eq!(node.activate(id).unwrap(), id);
        native_packets += 1;
        let after = node.read_active().unwrap().2;
        continuity_v1::check_state(&after, height, &c).unwrap();
        let capacity = continuity_v1::capacity(&after, height, &c).unwrap();
        assert_eq!(capacity.actual_keys, after.len());
        assert_eq!(capacity.credit_account_reserve, 0);
        assert_eq!(capacity.reward_queue_reserve, 20 - height.min(20) as usize);
        assert!(capacity.required_keys < continuity_v1::MAX_KEYS);
        if maintenance_only {
            assert!(capacity.required_keys <= previous_capacity.required_keys);
        }
        peak_required_keys = peak_required_keys.max(capacity.required_keys);
        assert_eq!(
            after[continuity_v1::MAINTENANCE_KEY]["useful_output_credit"],
            0
        );
        assert_eq!(
            after[continuity_v1::MAINTENANCE_KEY]["hardness_accepted"],
            false
        );
        if height == 1 {
            source_key = model_evidence::source_key(
                0,
                read_hash(&object(&after, first.contribution_id)["model_evidence_v3"]["source"]),
            );
            assert_eq!(after[&source_key]["intakes"], 2);
            assert_eq!(after[&source_key]["reserved_units"], 0);
            for cid in candidates {
                let evidence = model_evidence::evidence(&after, cid).unwrap();
                assert_eq!(evidence["candidate_correct"], 25);
                assert_eq!(evidence["parent_correct"], 3);
                assert_eq!(evidence["strongest_correct"], 19);
                assert_eq!(evidence["controls"].as_array().unwrap().len(), 4);
                assert_eq!(evidence["score"], POSITIVE_SCORE);
                assert_eq!(evidence["prospective_accepted"], false);
            }
            // The gate compares the historical controls and parent. The listed
            // components are not an independently verified derivation of the bundle.
            assert_eq!(capacity.archive_reserve, candidates.len());
        }
        if height < 48 {
            assert_eq!(capacity.archive_reserve, candidates.len());
        } else {
            assert_eq!(capacity.archive_reserve, 0);
        }
        if height == 48 {
            assert_eq!(previous_capacity.archive_reserve, candidates.len());
            assert_eq!(
                capacity.actual_keys,
                previous_capacity.actual_keys + candidates.len()
            );
            assert_eq!(capacity.required_keys, previous_capacity.required_keys);
            for cid in candidates {
                assert_eq!(object(&after, cid)["score"], POSITIVE_SCORE);
                assert_eq!(
                    evaluation::read_evaluation(&after, cid).unwrap()["closed"]["closed_height"],
                    48
                );
                assert!(after.contains_key(&format!("evaluation-archive:{}", hex::encode(cid))));
            }
        }
        if height == 56 {
            assert_eq!(after["model:current"], hex::encode(released));
            assert_eq!(after[&source_key]["reserved_units"], 100_000);
        }
        if height == 76 {
            let release_key = format!("release:{}", hex::encode(released));
            assert_eq!(after[&release_key]["remaining"], 0);
            for cid in [first.contribution_id, second.contribution_id] {
                assert_eq!(after[&release_key]["claims"][hex::encode(cid)], 50_000);
            }
            let before_reopen = node.read_active().unwrap();
            drop(node);
            node = Node::open(directory.path(), combined_settings.clone(), 2).unwrap();
            assert_eq!(node.read_active().unwrap(), before_reopen);
            assert_eq!(
                continuity_v1::capacity(&after, height, &c).unwrap(),
                capacity
            );
            continuity_v1::check_state(&node.read_active().unwrap().2, height, &c).unwrap();
        }
        if height == 128 {
            assert!(state.contains_key(&source_key));
            assert!(!after.keys().any(|key| key.starts_with("model-source-v3:")));
            for cid in candidates {
                assert!(model_evidence::evidence(&after, cid).is_ok());
                assert!(!after.contains_key(&format!("contribution:{}", hex::encode(cid))));
            }
        }
        if height == 304 {
            for cid in candidates {
                assert!(model_evidence::evidence(&after, cid).is_ok());
                assert!(after.contains_key(&format!("evaluation-archive:{}", hex::encode(cid))));
            }
            for prefix in &component_prefixes {
                assert!(after.keys().any(|key| key.starts_with(prefix)));
            }
        }
        if height == 305 || height == 306 {
            for cid in candidates {
                assert!(model_evidence::evidence(&after, cid).is_err());
                assert!(!after.contains_key(&format!("evaluation-archive:{}", hex::encode(cid))));
                assert!(!after
                    .keys()
                    .any(|key| key.starts_with(&evaluation::record_prefix(cid))));
            }
            for prefix in &component_prefixes {
                assert!(!after.keys().any(|key| key.starts_with(prefix)));
            }
            assert!(after
                .keys()
                .any(|key| key.starts_with(&current_model_prefix)));
            for key in &installed_model_keys {
                assert_eq!(after.get(key), initial.get(key));
            }
            assert_eq!(after["model:current"], hex::encode(released));
        }
        if [1, 48, 56, 76, 128, 256, 305, 306].contains(&height) {
            eprintln!("combined height {height}: {capacity:?}");
        }
    }
    assert_eq!(native_packets, 306);
    let completed = node.read_active().unwrap();
    drop(node);
    let reopened = Node::open(directory.path(), combined_settings, 1).unwrap();
    assert_eq!(reopened.read_active().unwrap(), completed);
    continuity_v1::check_state(&completed.2, 306, &c).unwrap();
    eprintln!(
        "combined lifecycle: native_packets={native_packets}, peak_required_keys={peak_required_keys}, full_capacity_fixture=false"
    );
}
