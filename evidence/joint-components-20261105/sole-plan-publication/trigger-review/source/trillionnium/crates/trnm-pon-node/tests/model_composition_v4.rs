//! Exact composition, ablation rewards, and durable native state transitions.
//! Every training row below is already public historical evaluation material.
//! These deliberately memorizing fixtures make no prospective efficacy claim.
use serde_json::{json, Value};
use trnm_crypto_primitives::{sign_hex, signing_key_from_hex};
use trnm_mvcc_fee::{
    continuity_v1, integer_factor_candidate_v2 as factor, model_composition_v4 as composition,
    model_evidence_v3,
    pon_commitment::{CacheLimits, CheckedExecutionParent, CheckedTransactionPrefix},
    pon_executor::{self, Config, ExecutionControl, PrefixContext, State},
    public_evaluation as evaluation,
};
use trnm_pon_node::{development_public, Node, Settings};
use trnm_protocol::{
    integer_factor_v2::FactorWitnessV2,
    pon_wire::{hash, Envelope, Hash, WireError},
};

const CLOCK: u64 = 1_800_100_000;
const FEATURES: usize = 257;

fn context() -> (Config, Settings) {
    (
        Config::installed_with_model_profiles(
            evaluation::PROFILE,
            continuity_v1::PROFILE,
            composition::PROFILE,
        )
        .unwrap(),
        Settings::development_with_model_profiles(
            None,
            evaluation::PROFILE,
            continuity_v1::PROFILE,
            composition::PROFILE,
        )
        .unwrap(),
    )
}
fn signing_key(who: u64) -> String {
    hex::encode(hash(b"DEV-ONLY-KEY", &[&who.to_le_bytes()]))
}
fn signed(c: &Config, who: u64, nonce: u64, tag: u8, payload: Vec<u8>) -> Vec<u8> {
    let key = signing_key_from_hex(&signing_key(who)).unwrap();
    let mut tx = Envelope {
        network: c.network,
        sender: development_public(who).unwrap(),
        nonce,
        expiry: 2000,
        fee_limit: 1_000_000,
        tag,
        payload,
        signature: [0; 64],
    };
    tx.signature = hex::decode(sign_hex(&key, &tx.signing_digest().unwrap()))
        .unwrap()
        .try_into()
        .unwrap();
    tx.encode().unwrap()
}
/// Sign the actual malformed bytes so order/duplicate refusals do not depend on
/// a bad signature. The ordinary producer API correctly refuses to encode them.
fn signed_noncanonical(c: &Config, nonce: u64, payload: &[u8]) -> Vec<u8> {
    let mut raw = b"PNX1".to_vec();
    raw.extend(c.network);
    raw.extend(development_public(3).unwrap());
    raw.extend(nonce.to_le_bytes());
    raw.extend(2000_u64.to_le_bytes());
    raw.extend(1_000_000_u64.to_le_bytes());
    raw.push(8);
    raw.extend(u16::try_from(payload.len()).unwrap().to_le_bytes());
    raw.extend(payload);
    let key = signing_key_from_hex(&signing_key(3)).unwrap();
    let signature = sign_hex(&key, &hash(b"tx-sign", &[&raw]));
    raw.extend(hex::decode(signature).unwrap());
    raw
}
fn account(state: &State, who: u64) -> &Value {
    &state[&format!("account:{}", hex::encode(development_public(who).unwrap()))]
}
fn nonce(state: &State, who: u64) -> u64 {
    account(state, who)["nonce"].as_u64().unwrap() + 1
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
fn rows() -> Vec<(Vec<i16>, usize)> {
    let policy: Value = serde_json::from_str(include_str!(
        "../../../../config/pon/model-evidence-v3.json"
    ))
    .unwrap();
    let tasks = policy["tasks"].as_array().unwrap();
    assert_eq!(tasks.len(), 25);
    tasks
        .iter()
        .map(|task| {
            let features = task["features"]
                .as_array()
                .unwrap()
                .iter()
                .map(|v| i16::try_from(v.as_i64().unwrap()).unwrap())
                .collect::<Vec<_>>();
            assert_eq!(features.len(), FEATURES);
            (features, task["label"].as_u64().unwrap() as usize)
        })
        .collect()
}
fn argmax(scores: &[i64; 3]) -> usize {
    let mut prediction = 0;
    for index in 1..3 {
        if scores[index] > scores[prediction] {
            prediction = index;
        }
    }
    prediction
}
fn dot(a: &[i16], b: &[i16]) -> i64 {
    a.iter()
        .zip(b)
        .map(|(&a, &b)| i64::from(a) * i64::from(b))
        .sum()
}
/// Deterministic perceptron visits, with the lowest class winning ties. Subtract
/// row zero after training: the returned rows are A for B=[[0,0],[1,0],[0,1]].
fn trained(rotation: usize, visits: usize) -> Vec<i16> {
    let rows = rows();
    let mut weights = [vec![0_i16; FEATURES], vec![0; FEATURES], vec![0; FEATURES]];
    for visit in 0..visits {
        let (features, target) = &rows[(rotation + visit) % rows.len()];
        let prediction = argmax(&weights.each_ref().map(|w| dot(w, features)));
        if prediction != *target {
            for (index, &feature) in features.iter().enumerate() {
                weights[prediction][index] -= feature;
                weights[*target][index] += feature;
            }
        }
    }
    weights[1..]
        .iter()
        .flat_map(|row| row.iter().zip(&weights[0]).map(|(&w, &base)| w - base))
        .collect()
}
fn add(a: &[i16], b: &[i16]) -> Vec<i16> {
    assert_eq!(a.len(), 2 * FEATURES);
    assert_eq!(a.len(), b.len());
    a.iter()
        .zip(b)
        .map(|(&a, &b)| a.checked_add(b).unwrap())
        .collect()
}
fn subtract(a: &[i16], b: &[i16]) -> Vec<i16> {
    assert_eq!(a.len(), b.len());
    a.iter()
        .zip(b)
        .map(|(&a, &b)| a.checked_sub(b).unwrap())
        .collect()
}
fn correct(model: &[i16]) -> u64 {
    rows()
        .iter()
        .filter(|(features, label)| {
            argmax(&[
                0,
                dot(&model[..FEATURES], features),
                dot(&model[FEATURES..], features),
            ]) == *label
        })
        .count() as u64
}
fn full_model(c: &Config, model: &[i16]) -> factor::IntegerModelV2 {
    let mut coefficients = vec![0; 5 * 3 * FEATURES];
    // Zero base and router select expert slot zero; normalized class row zero is zero.
    coefficients[7 * FEATURES..9 * FEATURES].copy_from_slice(model);
    factor::IntegerModelV2::from_coefficients(c.family, coefficients).unwrap()
}
fn stored_model(state: &State, c: &Config, id: Hash) -> factor::IntegerModelV2 {
    let prefix = format!("linear-model-v2:{}:", hex::encode(id));
    let chunks = state[&format!("{prefix}meta")]["chunks"].as_u64().unwrap();
    let mut bytes = Vec::new();
    for index in 0..chunks {
        bytes.extend(hex::decode(state[&format!("{prefix}{index:02}")].as_str().unwrap()).unwrap());
    }
    let model = factor::IntegerModelV2::decode(&bytes, c.family).unwrap();
    assert_eq!(model.id(), id);
    model
}
fn witness(
    state: &State,
    c: &Config,
    who: u64,
    round: u64,
    delta: &[i16],
    root: Hash,
) -> FactorWitnessV2 {
    let mut coefficients = vec![0, 0, 1, 0, 0, 1];
    coefficients.extend(delta);
    factor::build_witness(
        state,
        c,
        development_public(who).unwrap(),
        round,
        factor::FactorInputV2 {
            slot: 0,
            rank: 2,
            coefficients,
        },
        root,
    )
    .unwrap()
}
#[derive(Clone)]
struct Allocation {
    cid: Hash,
    who: u64,
    weight: u64,
}
impl Allocation {
    fn leaf(&self) -> Hash {
        hash(
            b"allocation-leaf",
            &[
                &self.cid,
                &development_public(self.who).unwrap(),
                &self.weight.to_le_bytes(),
            ],
        )
    }
}
fn pair(a: Hash, b: Hash) -> Hash {
    if a < b {
        hash(b"allocation-node", &[&a, &b])
    } else {
        hash(b"allocation-node", &[&b, &a])
    }
}
fn allocation_root(allocations: &[Allocation]) -> Hash {
    let mut leaves = allocations.iter().map(Allocation::leaf).collect::<Vec<_>>();
    while leaves.len() > 1 {
        if leaves.len() % 2 == 1 {
            leaves.push(*leaves.last().unwrap());
        }
        leaves = leaves.chunks_exact(2).map(|x| pair(x[0], x[1])).collect();
    }
    leaves[0]
}
struct Fixture {
    components: Vec<FactorWitnessV2>,
    bundle: FactorWitnessV2,
    allocations: Vec<Allocation>,
}
impl Fixture {
    fn new(
        state: &State,
        c: &Config,
        round: u64,
        deltas: &[Vec<i16>],
        bundle: &[i16],
        weights: &[u64],
    ) -> Self {
        assert_eq!(deltas.len(), weights.len());
        let components = deltas
            .iter()
            .enumerate()
            .map(|(who, delta)| witness(state, c, who as u64, round, delta, [8; 32]))
            .collect::<Vec<_>>();
        let mut allocations = components
            .iter()
            .zip(weights)
            .enumerate()
            .map(|(who, (component, &weight))| Allocation {
                cid: component.contribution_id,
                who: who as u64,
                weight,
            })
            .collect::<Vec<_>>();
        allocations.sort_by_key(|a| a.cid);
        let bundle = witness(state, c, 3, round, bundle, allocation_root(&allocations));
        Self {
            components,
            bundle,
            allocations,
        }
    }
    fn ids(&self) -> Vec<Hash> {
        self.components
            .iter()
            .chain(std::iter::once(&self.bundle))
            .map(|w| w.contribution_id)
            .collect()
    }
    fn submissions(&self, state: &State, c: &Config) -> Vec<Vec<u8>> {
        let mut txs = self
            .components
            .iter()
            .enumerate()
            .map(|(who, w)| {
                signed(
                    c,
                    who as u64,
                    nonce(state, who as u64),
                    23,
                    w.encode().unwrap(),
                )
            })
            .collect::<Vec<_>>();
        txs.push(signed(
            c,
            3,
            nonce(state, 3) + u64::from(self.components.len() == 4),
            23,
            self.bundle.encode().unwrap(),
        ));
        txs
    }
    fn release(&self, state: &State, c: &Config, budget: u64) -> (Hash, Vec<u8>) {
        release(state, c, &self.bundle, budget, &self.allocations)
    }
    fn claims(&self, state: &State, c: &Config, release: Hash) -> Vec<Vec<u8>> {
        assert_eq!(self.allocations.len(), 2);
        self.allocations
            .iter()
            .enumerate()
            .map(|(index, allocation)| {
                claim(
                    state,
                    c,
                    release,
                    allocation,
                    self.allocations[1 - index].leaf(),
                )
            })
            .collect()
    }
}
fn release(
    state: &State,
    c: &Config,
    bundle: &FactorWitnessV2,
    budget: u64,
    allocations: &[Allocation],
) -> (Hash, Vec<u8>) {
    let total: u64 = allocations.iter().map(|a| a.weight).sum();
    let root = allocation_root(allocations);
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
    for allocation in allocations {
        payload.extend(allocation.cid);
        payload.extend(allocation.weight.to_le_bytes());
    }
    (id, signed(c, 3, nonce(state, 3), 8, payload))
}
fn claim(
    state: &State,
    c: &Config,
    release: Hash,
    allocation: &Allocation,
    sibling: Hash,
) -> Vec<u8> {
    let mut payload = release.to_vec();
    payload.extend(allocation.cid);
    payload.extend(allocation.weight.to_le_bytes());
    payload.push(1);
    payload.extend(sibling);
    signed(c, allocation.who, nonce(state, allocation.who), 9, payload)
}
fn attestations(state: &State, c: &Config, ids: &[Hash], tag: u8) -> Vec<Vec<u8>> {
    let mut txs = Vec::new();
    let evaluators = if evaluation::quorum_enabled(c) {
        [0, 1, 3]
    } else {
        [0, 1, 2]
    };
    for who in evaluators {
        let mut next = nonce(state, who);
        for &cid in ids {
            if object(state, cid)["owner"] == hex::encode(development_public(who).unwrap()) {
                continue;
            }
            let evidence = composition::evidence(state, cid).unwrap();
            let round = evaluation::round(&object(state, cid)["public_evaluation"]).unwrap();
            let salt = [who as u8 + 1; 32];
            let score = evidence["score"].as_u64().unwrap();
            let digest = read_hash(&evidence["digest"]);
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
                            evidence: digest,
                            score,
                            salt,
                        },
                    )
                    .unwrap(),
                );
            } else {
                assert_eq!(tag, 15);
                payload.extend(c.plan);
                payload.extend(digest);
                payload.extend(score.to_le_bytes());
                payload.extend(salt);
            }
            txs.push(signed(c, who, next, tag, payload));
            next += 1;
        }
    }
    txs
}
fn append(node: &mut Node, parent: Hash, height: u64, txs: Vec<Vec<u8>>) -> Hash {
    assert_eq!(node.parent_height(parent).unwrap() + 1, height);
    let packet = node
        .make_consensus_maintenance(
            parent,
            txs,
            development_public(3).unwrap(),
            node.settings().genesis_time() + height * 10,
            4096,
        )
        .unwrap();
    assert_eq!(packet.header.height, height);
    assert_eq!(
        packet.header.work_task,
        continuity_v1::maintenance_task().unwrap()
    );
    let id = node.admit(&packet, CLOCK).unwrap();
    node.activate(id).unwrap();
    id
}
fn refuse(node: &Node, parent: Hash, height: u64, tx: Vec<u8>, expected: &str) {
    let active = node.read_active().unwrap();
    let error = node
        .make_consensus_maintenance(
            parent,
            vec![tx],
            development_public(3).unwrap(),
            node.settings().genesis_time() + height * 10,
            4096,
        )
        .unwrap_err();
    assert_eq!(error.to_string(), expected);
    assert_eq!(node.read_active().unwrap(), active);
}
fn step(state: &State, c: &Config, height: u64, txs: &[Vec<u8>]) -> State {
    pon_executor::execute(
        state,
        txs,
        height,
        development_public(3).unwrap(),
        [4; 32],
        4,
        c,
    )
    .unwrap_or_else(|error| panic!("native M06 height {height}: {error}"))
    .state
}

/// Continuity requires every intervening maturity/reward transition. Execute
/// them through M06; no artificial reward rows or sparse-height parent states.
fn advance_continuity(state: &State, c: &Config, from: u64, to: u64, txs: &[Vec<u8>]) -> State {
    assert!(continuity_v1::enabled(c) && from < to);
    assert!(to < c.params["subsidy_halving_interval"].as_u64().unwrap());
    let expected_issued = state["meta:issued"].as_u64().unwrap()
        + (to - from) * c.params["block_subsidy_units"].as_u64().unwrap();
    let maturity = c.params["reward_maturity_blocks"].as_u64().unwrap();
    let mut next = state.clone();
    for height in from + 1..=to {
        next = step(&next, c, height, if height == to { txs } else { &[] });
        let mut actual = next
            .range("reward:".to_owned()..)
            .take_while(|(key, _)| key.starts_with("reward:"))
            .map(|(_, value)| value["maturity"].as_u64().unwrap())
            .collect::<Vec<_>>();
        actual.sort_unstable();
        let expected = (height.saturating_sub(maturity) + 1..=height)
            .map(|mined| mined + maturity)
            .collect::<Vec<_>>();
        assert_eq!(actual, expected, "complete native reward queue at {height}");
    }
    assert_eq!(next["meta:issued"], expected_issued);
    next
}

#[test]
fn quorum_profile_replays_two_composition_generations_and_zero_score_components() {
    let c = Config::installed_with_model_profiles(
        evaluation::QUORUM_PROFILE,
        continuity_v1::PROFILE,
        composition::PROFILE,
    )
    .unwrap();
    let settings = Settings::development_with_model_profiles(
        None,
        evaluation::QUORUM_PROFILE,
        continuity_v1::PROFILE,
        composition::PROFILE,
    )
    .unwrap();
    let directory = tempfile::tempdir().unwrap();
    let node = Node::open(directory.path(), settings, 4).unwrap();
    let initial = node.read_active().unwrap().2;
    let a = trained(0, 10);
    let b = trained(16, 10);
    let parent = add(&a, &b);
    let target = add(&trained(0, 25), &trained(1, 25));
    assert_eq!(
        [correct(&a), correct(&b), correct(&parent), correct(&target)],
        [21, 21, 24, 25]
    );
    let first = Fixture::new(&initial, &c, 0, &[a, b], &parent, &[120_000, 120_000]);
    let mut state = step(&initial, &c, 1, &first.submissions(&initial, &c));
    for (from, height, tag) in [(1, 16, 14), (16, 32, 15)] {
        state = advance_continuity(
            &state,
            &c,
            from,
            height,
            &attestations(&state, &c, &first.ids(), tag),
        );
    }
    state = advance_continuity(&state, &c, 32, 48, &[]);
    for cid in first.ids() {
        let e = evaluation::read_evaluation(&state, cid).unwrap();
        assert_eq!(e["closed"]["matching_reveal_count"], 2);
        assert_eq!(e["closed"]["missing_reveal_count"], 1);
    }
    let (first_release, tx) = first.release(&state, &c, 1000);
    state = advance_continuity(&state, &c, 48, 56, &[tx]);
    assert_eq!(state["model:current"], hex::encode(first_release));
    state = advance_continuity(&state, &c, 56, 76, &first.claims(&state, &c, first_release));
    let paid = &state[&format!("release:{}", hex::encode(first_release))];
    assert_eq!(paid["remaining"], 0);
    for allocation in &first.allocations {
        assert_eq!(paid["claims"][hex::encode(allocation.cid)], 500);
    }
    state = advance_continuity(&state, &c, 76, 128, &[]);
    // Consecutive M06 execution is distinct from a PNW1 packet history.
    // Both zero-standalone-gain components have positive exact bundle marginals.
    let mut z = vec![0_i16; 2 * FEATURES];
    z[FEATURES - 1] = -32;
    let absolute = [add(&parent, &z), subtract(&target, &z)];
    assert_eq!([correct(&absolute[0]), correct(&absolute[1])], [23, 23]);
    let deltas = absolute
        .iter()
        .map(|model| subtract(model, &parent))
        .collect::<Vec<_>>();
    let second = Fixture::new(
        &state,
        &c,
        1,
        &deltas,
        &subtract(&target, &parent),
        &[80_000, 80_000],
    );
    assert_eq!(second.bundle.parent_ref, first_release);
    state = step(&state, &c, 129, &second.submissions(&state, &c));
    for component in &second.components {
        assert_eq!(
            composition::evidence(&state, component.contribution_id).unwrap()["score"],
            0
        );
    }
    for (from, height, tag) in [(129, 144, 14), (144, 160, 15)] {
        state = advance_continuity(
            &state,
            &c,
            from,
            height,
            &attestations(&state, &c, &second.ids(), tag),
        );
    }
    state = advance_continuity(&state, &c, 160, 176, &[]);
    let cid = second.components[0].contribution_id;
    let e = evaluation::read_evaluation(&state, cid).unwrap();
    assert_eq!(e["closed"]["score"], 0);
    assert_eq!(e["closed"]["status"], "complete-scored");
    assert_eq!(e["plan"]["generation"], 1);
    assert_eq!(e["plan"]["parent"], hex::encode(first_release));
    let mut payload = cid.to_vec();
    payload.extend(evaluation::closed_digest(&e).unwrap());
    payload.extend([1; 32]);
    payload.extend([2; 32]);
    state = step(
        &state,
        &c,
        177,
        &[signed(&c, 0, nonce(&state, 0), 17, payload)],
    );
    let (second_release, tx) = second.release(&state, &c, 1000);
    state = advance_continuity(&state, &c, 177, 184, &[tx]);
    assert_eq!(state["model:current"], hex::encode(second_release));
    assert_ne!(first_release, second_release);
    assert_eq!(
        stored_model(&state, &c, second.bundle.candidate_artifact),
        full_model(&c, &target)
    );
    assert_eq!(
        composition::evidence(&state, second.bundle.contribution_id).unwrap()["candidate_correct"],
        25
    );
    state = advance_continuity(
        &state,
        &c,
        184,
        204,
        &second.claims(&state, &c, second_release),
    );
    let paid = &state[&format!("release:{}", hex::encode(second_release))];
    assert_eq!(paid["remaining"], 0);
    for allocation in &second.allocations {
        assert_eq!(paid["claims"][hex::encode(allocation.cid)], 500);
    }
    // The fixed public rows are now saturated. This is two bounded empirical
    // updates, not untouched future-data activation or unlimited improvement.
}
fn prefix<'a>(
    state: &'a State,
    c: &Config,
    height: u64,
    parent_id: Hash,
) -> CheckedTransactionPrefix<'a> {
    let progress = |_| Ok::<_, &'static str>(());
    CheckedExecutionParent::bind(
        state,
        pon_executor::root(state).unwrap(),
        None,
        CacheLimits::default(),
    )
    .unwrap()
    .into_prefix_with_control(
        PrefixContext {
            timestamp: None,
            height,
            miner: development_public(3).unwrap(),
            parent_id,
        },
        c,
        &ExecutionControl::new(&progress, &()),
    )
    .unwrap()
}
/// Same signed transactions and actual parent state through two separate M06
/// execution paths; compare every growing prefix, including receipts and roots.
fn compare_prefixes(
    state: &State,
    c: &Config,
    height: u64,
    parent_id: Hash,
    txs: &[Vec<u8>],
) -> pon_executor::Output {
    let mut prefix = prefix(state, c, height, parent_id);
    let mut last = None;
    for end in 1..=txs.len() {
        let staged = prefix.execute(&txs[..end]).unwrap();
        let full = pon_executor::execute(
            state,
            &txs[..end],
            height,
            development_public(3).unwrap(),
            parent_id,
            4,
            c,
        )
        .unwrap();
        assert_eq!(staged.output.state, full.state);
        assert_eq!(staged.output.receipts, full.receipts);
        assert_eq!(staged.output.root, full.root);
        assert_eq!(staged.output.metrics.signature_verifications, 1);
        assert_eq!(prefix.len(), end);
        last = Some(staged.output);
    }
    last.unwrap()
}
fn rejected_prefix_keeps_prior_transaction(
    state: &State,
    c: &Config,
    height: u64,
    rejected: Vec<u8>,
    expected: &str,
) {
    let mut payload = development_public(3).unwrap().to_vec();
    payload.extend(1_u64.to_le_bytes());
    let transfer = signed(c, 2, nonce(state, 2), 1, payload);
    let mut prefix = prefix(state, c, height, [4; 32]);
    let accepted = vec![transfer.clone()];
    let before = prefix.execute(&accepted).unwrap().output;
    assert_eq!(prefix.execute(&[transfer, rejected]).unwrap_err(), expected);
    assert_eq!(prefix.len(), 1);
    let after = prefix.execute(&accepted).unwrap().output;
    assert_eq!(after.state, before.state);
    assert_eq!(after.receipts, before.receipts);
    assert_eq!(after.root, before.root);
    let full = pon_executor::execute(
        state,
        &accepted,
        height,
        development_public(3).unwrap(),
        [4; 32],
        4,
        c,
    )
    .unwrap();
    assert_eq!(after.state, full.state);
    assert_eq!(after.receipts, full.receipts);
    assert_eq!(after.root, full.root);
}
fn assert_record(
    state: &State,
    c: &Config,
    fixture: &Fixture,
    released: Hash,
    models: &[Vec<i16>],
    bundle_correct: u64,
    strongest: u64,
) {
    let record = &state[&format!("release:{}", hex::encode(released))]["model_composition_v4"];
    assert_eq!(record["schema"], "native-model-composition-record-v4");
    assert_eq!(record["zero_subset_checks"], 1);
    assert_eq!(record["correct"], bundle_correct);
    assert_eq!(record["strongest_correct"], strongest);
    assert_eq!(record["gain_score"], (bundle_correct - strongest) * 40_000);
    assert_eq!(
        record["total_weight"],
        fixture.allocations.iter().map(|a| a.weight).sum::<u64>()
    );
    assert_eq!(record["parent"], hex::encode(fixture.bundle.parent_ref));
    assert_eq!(
        record["parent_artifact"],
        hex::encode(fixture.bundle.parent_artifact)
    );
    assert_eq!(
        record["artifact"],
        hex::encode(fixture.bundle.candidate_artifact)
    );
    assert_eq!(record["rows"], 25);
    for flag in [
        "prospective_accepted",
        "independent_accepted",
        "public_reward_eligible",
        "shapley_fairness_accepted",
    ] {
        assert_eq!(record[flag], false);
    }
    let components = record["components"].as_array().unwrap();
    assert_eq!(components.len(), 2);
    for (actual, allocation) in components.iter().zip(&fixture.allocations) {
        let index = allocation.who as usize;
        assert_eq!(actual["contribution"], hex::encode(allocation.cid));
        assert_eq!(
            actual["owner"],
            hex::encode(development_public(allocation.who).unwrap())
        );
        assert_eq!(
            actual["artifact"],
            hex::encode(full_model(c, &models[index]).id())
        );
        assert_eq!(actual["correct"], correct(&models[index]));
        assert_eq!(
            actual["without_artifact"],
            hex::encode(full_model(c, &models[1 - index]).id())
        );
        assert_eq!(actual["without_correct"], correct(&models[1 - index]));
        assert_eq!(actual["weight"], allocation.weight);
    }
    let digest = read_hash(&record["digest"]);
    let mut unsigned = record.clone();
    unsigned.as_object_mut().unwrap().remove("digest");
    assert_eq!(
        digest,
        hash(
            b"native-model-composition-record-v4",
            &[&serde_json::to_vec(&unsigned).unwrap()]
        )
    );
}

/// Optional observations from actual signed native execution. Python recomputes
/// its answers from the retained full model bytes, never from fixture scores.
fn observe(name: &str, kind: &str, input: Value, native: Value) {
    let Ok(directory) = std::env::var("TRNM_MODEL_COMPOSITION_VECTORS") else {
        return;
    };
    let run_id = std::env::var("TRNM_MODEL_COMPOSITION_RUN_ID").expect("explicit fresh run id");
    assert!(!run_id.is_empty() && run_id.len() <= 256);
    std::fs::create_dir_all(&directory).unwrap();
    let path = std::path::Path::new(&directory).join(format!("{kind}-{name}.json"));
    let file = std::fs::OpenOptions::new()
        .write(true)
        .create_new(true)
        .open(path)
        .expect("fresh observations must not overwrite a prior run");
    serde_json::to_writer(
        file,
        &json!({
            "schema":"model-composition-native-observation-v1", "run_id":run_id,
            "kind":kind,"name":name,"input":input,"native":native,
            "scope":"native-observation-for-independent-model-conformance-only",
            "economic_accepted":false,"independent_operators_accepted":false,
            "public_reward_eligible":false
        }),
    )
    .unwrap();
}

fn source_reservations(state: &State, round: u64) -> Value {
    let prefix = format!("model-source-v4:{round}:");
    Value::Object(
        state
            .iter()
            .filter(|(key, _)| key.starts_with(&prefix))
            .map(|(_, value)| {
                (
                    value["source"].as_str().unwrap().to_owned(),
                    value["reserved_units"].clone(),
                )
            })
            .collect(),
    )
}

fn observe_release(
    name: &str,
    before: &State,
    c: &Config,
    fixture: &Fixture,
    budget: u64,
    outcome: Result<&State, &str>,
) {
    if std::env::var_os("TRNM_MODEL_COMPOSITION_VECTORS").is_none() {
        return;
    }
    let parent_ref = read_hash(&before["model:current"]);
    let parent_artifact = before
        .get(&format!("release:{}", hex::encode(parent_ref)))
        .map(|record| read_hash(&record["artifact"]))
        .unwrap_or(parent_ref);
    let item = |cid: Hash| {
        let contribution = object(before, cid);
        json!({"id":hex::encode(cid),"contribution":contribution,
            "model_hex":hex::encode(stored_model(before,c,read_hash(&contribution["artifact"])).encode()),
            "native_evidence":composition::evidence(before,cid).unwrap()})
    };
    let components: Vec<_> = fixture
        .allocations
        .iter()
        .map(|allocation| {
            let mut value = item(allocation.cid);
            value["weight"] = json!(allocation.weight);
            value
        })
        .collect();
    let (released, transaction) = fixture.release(before, c, budget);
    let input = json!({
        "context":{"network":hex::encode(c.network),"parameters":hex::encode(c.parameters),
            "family":hex::encode(c.family),"plan":hex::encode(c.plan)},
        "parent_ref":hex::encode(parent_ref),
        "parent_model_hex":hex::encode(stored_model(before,c,parent_artifact).encode()),
        "bundle":item(fixture.bundle.contribution_id),"components":components,"budget":budget,
        "source_reserved":source_reservations(before,fixture.bundle.round),
        "release":hex::encode(released),"signed_release_hex":hex::encode(transaction)
    });
    let native = match outcome {
        Ok(after) => json!({"error":null,
            "release":after[&format!("release:{}",hex::encode(released))],
            "source_reserved":source_reservations(after,fixture.bundle.round)}),
        Err(error) => json!({"error":error}),
    };
    observe(name, "release", input, native);
}

fn observe_claims(name: &str, state: &State, released: Hash) {
    let record = &state[&format!("release:{}", hex::encode(released))];
    observe(
        name,
        "claims",
        json!({"release":hex::encode(released)}),
        json!({"claims":record["claims"],"remaining":record["remaining"]}),
    );
}

#[test]
fn native_composition_rewards_reorg_reopen_and_continuity_cleanup() {
    let directory = tempfile::tempdir().unwrap();
    let (c, settings) = context();
    assert_eq!(c.params["consensus_revision"], composition::REVISION);
    assert_eq!(composition::REVISION, 14);
    let standalone = [
        Settings::development_with_profiles(None, evaluation::PROFILE, continuity_v1::PROFILE)
            .unwrap(),
        Settings::development_with_model_profiles(
            None,
            evaluation::PROFILE,
            "legacy-task-v1",
            composition::PROFILE,
        )
        .unwrap(),
        Settings::development_with_model_profiles(
            None,
            evaluation::PROFILE,
            continuity_v1::PROFILE,
            model_evidence_v3::PROFILE,
        )
        .unwrap(),
    ];
    for other in standalone {
        assert_ne!(settings.network(), other.network());
        assert_ne!(settings.parameters(), other.parameters());
        assert_ne!(settings.genesis(), other.genesis());
    }
    let mut node = Node::open(directory.path(), settings.clone(), 4).unwrap();
    let initial = node.read_active().unwrap().2;
    assert_eq!(
        node.make(
            settings.genesis(),
            vec![],
            development_public(3).unwrap(),
            settings.genesis_time() + 10,
            4096
        )
        .unwrap_err()
        .to_string(),
        "EXPLICIT_TASK_REQUIRED"
    );
    let a = trained(0, 25);
    let b = trained(1, 25);
    let sum = add(&a, &b);
    assert_eq!([correct(&a), correct(&b), correct(&sum)], [24, 23, 25]);
    let models = [a.clone(), b.clone()];
    let fixture = Fixture::new(&initial, &c, 0, &models, &sum, &[80_000, 40_000]);
    let ids = fixture.ids();
    assert_eq!(fixture.bundle.candidate_artifact, full_model(&c, &sum).id());
    let installed_keys = initial
        .keys()
        .filter(|key| key.starts_with("linear-model-v2:"))
        .cloned()
        .collect::<Vec<_>>();
    let component_prefixes = fixture
        .components
        .iter()
        .map(|w| format!("linear-model-v2:{}:", hex::encode(w.candidate_artifact)))
        .collect::<Vec<_>>();
    let mut tip = settings.genesis();
    let mut closed_tip = tip;
    let mut released = [0; 32];
    let mut source_key = String::new();
    let mut native_packets = 0;
    let mut peak_required = continuity_v1::capacity(&initial, 0, &c)
        .unwrap()
        .required_keys;
    for height in 1..=306 {
        if height == 77 {
            // Every fork height is a real PNW1 packet. A timely signed objection
            // changes the better-work branch; it cannot fabricate a replacement model.
            let mut fork = closed_tip;
            for fork_height in 49..=77 {
                let state = node.state_at(fork).unwrap();
                let txs = if fork_height == 49 {
                    let closed =
                        evaluation::read_evaluation(&state, fixture.bundle.contribution_id)
                            .unwrap();
                    let mut payload = fixture.bundle.contribution_id.to_vec();
                    payload.extend(evaluation::closed_digest(&closed).unwrap());
                    payload.extend([1; 32]);
                    payload.extend([2; 32]);
                    vec![signed(&c, 0, nonce(&state, 0), 17, payload)]
                } else {
                    vec![]
                };
                if fork_height == 56 {
                    refuse(
                        &node,
                        fork,
                        fork_height,
                        fixture.release(&state, &c, 100_001).1,
                        "MODEL_EVIDENCE_REVIEW_HOLD",
                    );
                }
                fork = append(&mut node, fork, fork_height, txs);
                native_packets += 1;
            }
            assert_eq!(node.active().unwrap().0, fork);
            let rolled_back = node.read_active().unwrap();
            assert_eq!(rolled_back.2["model:current"], initial["model:current"]);
            assert!(!rolled_back
                .2
                .contains_key(&format!("release:{}", hex::encode(released))));
            assert_eq!(rolled_back.2[&source_key]["reserved_units"], 0);
            assert_eq!(rolled_back.2[&source_key]["intakes"], 2);
            assert_eq!(
                object(&rolled_back.2, fixture.bundle.contribution_id)["status"],
                "expired"
            );
            continuity_v1::check_state(&rolled_back.2, 77, &c).unwrap();
            drop(node);
            node = Node::open(directory.path(), settings.clone(), 2).unwrap();
            assert_eq!(node.read_active().unwrap(), rolled_back);
            eprintln!(
                "v4 native fork77: release, claims and source reservation rolled back; reopened"
            );
        }
        // The original chain is extended through77 and78, including the height
        // where it is not yet the best-work branch. No height is silently skipped.
        let state = node.state_at(tip).unwrap();
        let previous_capacity = continuity_v1::capacity(&state, height - 1, &c).unwrap();
        let txs = match height {
            1 => fixture.submissions(&state, &c),
            16 => attestations(&state, &c, &ids, 14),
            32 => attestations(&state, &c, &ids, 15),
            56 => {
                // The aliases share one cap. Integer floor payouts consume100000
                // from a100001 budget, while a100002 budget would consume100002.
                refuse(
                    &node,
                    tip,
                    height,
                    fixture.release(&state, &c, 100_002).1,
                    "MODEL_EVIDENCE_SOURCE_BUDGET",
                );
                rejected_prefix_keeps_prior_transaction(
                    &state,
                    &c,
                    height,
                    fixture.release(&state, &c, 100_002).1,
                    "MODEL_EVIDENCE_SOURCE_BUDGET",
                );
                if std::env::var_os("TRNM_MODEL_COMPOSITION_VECTORS").is_some() {
                    let error = pon_executor::execute(
                        &state,
                        &[fixture.release(&state, &c, 100_002).1],
                        height,
                        development_public(3).unwrap(),
                        tip,
                        4,
                        &c,
                    )
                    .unwrap_err();
                    observe_release("source-cap", &state, &c, &fixture, 100_002, Err(error));
                }
                let mut wrong = fixture.allocations.clone();
                wrong[0].weight += 1;
                refuse(
                    &node,
                    tip,
                    height,
                    release(&state, &c, &fixture.bundle, 100_001, &wrong).1,
                    "ROOT",
                );
                let (id, tx) = fixture.release(&state, &c, 100_001);
                released = id;
                vec![tx]
            }
            75 => {
                refuse(
                    &node,
                    tip,
                    height,
                    fixture.claims(&state, &c, released)[0].clone(),
                    "STATE",
                );
                vec![]
            }
            76 => {
                let mut manipulated = fixture.allocations[0].clone();
                manipulated.weight += 1;
                refuse(
                    &node,
                    tip,
                    height,
                    claim(
                        &state,
                        &c,
                        released,
                        &manipulated,
                        fixture.allocations[1].leaf(),
                    ),
                    "ROOT",
                );
                fixture.claims(&state, &c, released)
            }
            _ => vec![],
        };
        let empty = txs.is_empty();
        let prefix_expected = (!empty).then(|| compare_prefixes(&state, &c, height, tip, &txs));
        let claim_fees = txs
            .iter()
            .map(|raw| {
                let tx = Envelope::decode(raw).unwrap();
                (
                    tx.sender,
                    c.fees[tx.tag as usize]
                        + raw.len() as u64 * c.params["byte_fee_units"].as_u64().unwrap(),
                )
            })
            .collect::<Vec<_>>();
        tip = append(&mut node, tip, height, txs);
        native_packets += 1;
        let after = node.state_at(tip).unwrap();
        if let Some(expected) = prefix_expected {
            assert_eq!(after, expected.state);
            assert_eq!(pon_executor::root(&after).unwrap(), expected.root);
        }
        continuity_v1::check_state(&after, height, &c).unwrap();
        let capacity = continuity_v1::capacity(&after, height, &c).unwrap();
        assert_eq!(capacity.actual_keys, after.len());
        assert_eq!(capacity.credit_account_reserve, 0);
        assert_eq!(capacity.reward_queue_reserve, 20 - height.min(20) as usize);
        assert!(capacity.required_keys < continuity_v1::MAX_KEYS);
        if empty {
            assert!(capacity.required_keys <= previous_capacity.required_keys);
        }
        peak_required = peak_required.max(capacity.required_keys);
        assert_eq!(
            capacity.archive_reserve,
            if height < 48 { ids.len() } else { 0 }
        );
        assert_eq!(
            after[continuity_v1::MAINTENANCE_KEY]["useful_output_credit"],
            0
        );
        assert_eq!(
            after[continuity_v1::MAINTENANCE_KEY]["hardness_accepted"],
            false
        );
        if height == 1 {
            for (index, &cid) in ids.iter().enumerate() {
                let evidence = composition::evidence(&after, cid).unwrap();
                assert_eq!(
                    evidence["schema"],
                    "native-integer-model-evidence-record-v4"
                );
                assert_eq!(evidence["candidate_correct"], [24, 23, 25][index]);
                assert_eq!(evidence["parent_correct"], 3);
                assert_eq!(evidence["strongest_correct"], 19);
                assert_eq!(evidence["score"], [200_000, 160_000, 240_000][index]);
                assert_eq!(
                    evidence["controls"]
                        .as_array()
                        .unwrap()
                        .iter()
                        .map(|v| v["correct"].as_u64().unwrap())
                        .collect::<Vec<_>>(),
                    [18, 19, 19, 19]
                );
                assert_eq!(
                    object(&after, cid)["model_evidence_v4"]["digest"],
                    evidence["digest"]
                );
                assert!(model_evidence_v3::evidence(&after, cid).is_err());
            }
            let first_source = &object(&after, ids[0])["model_evidence_v4"]["source"];
            assert_eq!(
                *first_source,
                object(&after, ids[1])["model_evidence_v4"]["source"]
            );
            source_key = composition::source_key(0, read_hash(first_source));
            assert_eq!(after[&source_key]["intakes"], 2);
            assert_eq!(after[&source_key]["reserved_units"], 0);
        }
        if height == 48 {
            closed_tip = tip;
            assert_eq!(previous_capacity.archive_reserve, 3);
            assert_eq!(capacity.actual_keys, previous_capacity.actual_keys + 3);
            assert_eq!(capacity.required_keys, previous_capacity.required_keys);
            for &cid in &ids {
                assert_eq!(
                    evaluation::read_evaluation(&after, cid).unwrap()["closed"]["closed_height"],
                    48
                );
                assert!(after.contains_key(&format!("evaluation-archive:{}", hex::encode(cid))));
            }
        }
        if height == 56 {
            observe_release("asymmetric", &state, &c, &fixture, 100_001, Ok(&after));
            assert_eq!(after["model:current"], hex::encode(released));
            assert_eq!(after[&source_key]["reserved_units"], 100_000);
            assert_record(&after, &c, &fixture, released, &models, 25, 24);
            assert_eq!(
                stored_model(&after, &c, fixture.bundle.candidate_artifact),
                full_model(&c, &sum)
            );
        }
        if height == 76 {
            observe_claims("asymmetric", &after, released);
            let record = &after[&format!("release:{}", hex::encode(released))];
            assert_eq!(record["remaining"], 1);
            assert_eq!(record["budget"], 100_001);
            assert_eq!(record["deadline"], 1076);
            for allocation in &fixture.allocations {
                let amount = if allocation.who == 0 { 66_667 } else { 33_333 };
                assert_eq!(record["claims"][hex::encode(allocation.cid)], amount);
                let fee = claim_fees
                    .iter()
                    .find(|(sender, _)| *sender == development_public(allocation.who).unwrap())
                    .unwrap()
                    .1;
                assert_eq!(
                    account(&after, allocation.who)["balance"].as_u64().unwrap(),
                    account(&state, allocation.who)["balance"].as_u64().unwrap() + amount - fee
                );
            }
            refuse(
                &node,
                tip,
                77,
                fixture.claims(&after, &c, released)[0].clone(),
                "DUPLICATE",
            );
            let paid = node.read_active().unwrap();
            drop(node);
            node = Node::open(directory.path(), settings.clone(), 2).unwrap();
            assert_eq!(node.read_active().unwrap(), paid);
        }
        if height == 78 {
            assert_eq!(node.active().unwrap().0, tip);
            assert_eq!(after["model:current"], hex::encode(released));
            assert_eq!(after[&source_key]["reserved_units"], 100_000);
            assert_eq!(
                after[&format!("release:{}", hex::encode(released))]["remaining"],
                1
            );
            assert_record(&after, &c, &fixture, released, &models, 25, 24);
        }
        if height == 128 {
            assert!(state.contains_key(&source_key));
            assert!(!after.keys().any(|key| key.starts_with("model-source-v4:")));
        }
        if height == 304 {
            for &cid in &ids {
                assert!(composition::evidence(&after, cid).is_ok());
                assert!(after.contains_key(&format!("evaluation-archive:{}", hex::encode(cid))));
            }
            for prefix in &component_prefixes {
                assert!(after.keys().any(|key| key.starts_with(prefix)));
            }
        }
        if height == 305 || height == 306 {
            for &cid in &ids {
                assert!(composition::evidence(&after, cid).is_err());
                assert!(!after.contains_key(&format!("evaluation-archive:{}", hex::encode(cid))));
                assert!(!after
                    .keys()
                    .any(|key| key.starts_with(&evaluation::record_prefix(cid))));
            }
            for prefix in &component_prefixes {
                assert!(!after.keys().any(|key| key.starts_with(prefix)));
            }
            for key in &installed_keys {
                assert_eq!(after.get(key), initial.get(key));
            }
            assert_eq!(
                stored_model(&after, &c, fixture.bundle.candidate_artifact),
                full_model(&c, &sum)
            );
            assert_record(&after, &c, &fixture, released, &models, 25, 24);
        }
        if [1, 48, 56, 76, 78, 128, 305, 306].contains(&height) {
            eprintln!("v4 native height{height}: {capacity:?}");
        }
    }
    assert_eq!(native_packets, 335);
    let completed = node.read_active().unwrap();
    assert_eq!(completed.0, tip);
    drop(node);
    let reopened = Node::open(directory.path(), settings, 1).unwrap();
    assert_eq!(reopened.read_active().unwrap(), completed);

    // Expiry is a separate contiguous M06 execution from native height306. These
    // 770 transitions do not claim 770 additional PNW1 mining/verifying packets.
    let release_key = format!("release:{}", hex::encode(released));
    let publisher = hex::encode(development_public(3).unwrap());
    let mut state = completed.2;
    for height in 307..=1076 {
        if height == 1076 {
            assert_eq!(state[&release_key]["remaining"], 1);
            assert_eq!(state[&release_key]["status"], "open");
            let matured: u64 = state
                .iter()
                .filter(|(key, value)| {
                    key.starts_with("reward:")
                        && value["owner"] == publisher
                        && value["maturity"].as_u64().unwrap() <= height
                })
                .map(|(_, value)| value["amount"].as_u64().unwrap())
                .sum();
            let balance = account(&state, 3)["balance"].as_u64().unwrap();
            state = step(&state, &c, height, &[]);
            assert_eq!(
                account(&state, 3)["balance"].as_u64().unwrap(),
                balance + matured + 1
            );
        } else {
            state = step(&state, &c, height, &[]);
        }
    }
    assert_eq!(state[&release_key]["remaining"], 0);
    assert_eq!(state[&release_key]["status"], "expired");
    continuity_v1::check_state(&state, 1076, &c).unwrap();
    eprintln!("v4 lifecycle: native_packets={native_packets}, direct_expiry_transitions=770, peak_required_keys={peak_required}, full_capacity_fixture=false");
}

#[test]
fn two_native_generations_use_the_actual_nonzero_parent_once() {
    let directory = tempfile::tempdir().unwrap();
    let (c, settings) = context();
    let mut node = Node::open(directory.path(), settings.clone(), 4).unwrap();
    let initial = node.read_active().unwrap().2;
    let a = trained(0, 10);
    let b = trained(16, 10);
    let parent = add(&a, &b);
    let target = add(&trained(0, 25), &trained(1, 25));
    assert_eq!(
        [correct(&a), correct(&b), correct(&parent), correct(&target)],
        [21, 21, 24, 25]
    );
    let first_models = [a, b];
    let first = Fixture::new(&initial, &c, 0, &first_models, &parent, &[120_000, 120_000]);
    // These are actual absolute child models. Their witnesses will be built
    // relative to the admitted release at128, never an injected database parent.
    let mut z = vec![0_i16; 2 * FEATURES];
    z[FEATURES - 1] = -32;
    let second_models = [add(&parent, &z), subtract(&target, &z)];
    assert_eq!(
        [correct(&second_models[0]), correct(&second_models[1])],
        [23, 23]
    );
    assert_eq!(
        subtract(&add(&second_models[0], &second_models[1]), &parent),
        target
    );
    let mut second = None;
    let mut first_release = [0; 32];
    let mut second_release = [0; 32];
    let mut tip = settings.genesis();
    for height in 1..=204 {
        let state = node.read_active().unwrap().2;
        if height == 129 {
            assert_eq!(state["model:current"], hex::encode(first_release));
            assert_ne!(state["model:current"], initial["model:current"]);
            assert_eq!(
                stored_model(&state, &c, first.bundle.candidate_artifact),
                full_model(&c, &parent)
            );
            let deltas = second_models
                .iter()
                .map(|m| subtract(m, &parent))
                .collect::<Vec<_>>();
            let fixture = Fixture::new(
                &state,
                &c,
                1,
                &deltas,
                &subtract(&target, &parent),
                &[80_000, 80_000],
            );
            for witness in fixture
                .components
                .iter()
                .chain(std::iter::once(&fixture.bundle))
            {
                assert_eq!(witness.parent_ref, first_release);
                assert_eq!(witness.parent_artifact, first.bundle.candidate_artifact);
                assert_eq!(witness.rank, 2);
                assert_eq!(witness.slot, 0);
                assert_eq!(witness.round, 1);
            }
            assert_eq!(
                fixture.bundle.candidate_artifact,
                full_model(&c, &target).id()
            );
            second = Some(fixture);
        }
        let txs = match height {
            1 => first.submissions(&state, &c),
            16 => attestations(&state, &c, &first.ids(), 14),
            32 => attestations(&state, &c, &first.ids(), 15),
            56 => {
                let (id, tx) = first.release(&state, &c, 100_000);
                first_release = id;
                vec![tx]
            }
            57 => {
                // A fresh valid outer signature cannot reuse the prior full
                // parent after the real first-generation release was adopted.
                let stale = signed(
                    &c,
                    0,
                    nonce(&state, 0),
                    23,
                    first.components[0].encode().unwrap(),
                );
                refuse(&node, tip, height, stale, "FACTOR_PARENT");
                refuse(
                    &node,
                    tip,
                    height,
                    first.release(&state, &c, 100_000).1,
                    "STATE",
                );
                vec![]
            }
            76 => first.claims(&state, &c, first_release),
            129 => second.as_ref().unwrap().submissions(&state, &c),
            144 => attestations(&state, &c, &second.as_ref().unwrap().ids(), 14),
            160 => attestations(&state, &c, &second.as_ref().unwrap().ids(), 15),
            184 => {
                let (id, tx) = second.as_ref().unwrap().release(&state, &c, 100_000);
                second_release = id;
                vec![tx]
            }
            204 => second.as_ref().unwrap().claims(&state, &c, second_release),
            _ => vec![],
        };
        tip = append(&mut node, tip, height, txs);
        let after = node.read_active().unwrap().2;
        continuity_v1::check_state(&after, height, &c).unwrap();
        if height == 56 {
            observe_release("first-generation", &state, &c, &first, 100_000, Ok(&after));
            assert_record(&after, &c, &first, first_release, &first_models, 24, 21);
            assert_eq!(after["model:current"], hex::encode(first_release));
        }
        if height == 76 {
            observe_claims("first-generation", &after, first_release);
            assert_eq!(
                after[&format!("release:{}", hex::encode(first_release))]["remaining"],
                0
            );
        }
        if height == 128 {
            assert!(!after.keys().any(|key| key.starts_with("model-source-v4:")));
            let before = node.read_active().unwrap();
            drop(node);
            node = Node::open(directory.path(), settings.clone(), 2).unwrap();
            assert_eq!(node.read_active().unwrap(), before);
        }
        if height == 129 || height == 176 {
            let fixture = second.as_ref().unwrap();
            for (index, cid) in fixture.ids().into_iter().enumerate() {
                let evidence = composition::evidence(&after, cid).unwrap();
                assert_eq!(evidence["parent_correct"], 24);
                assert_eq!(evidence["strongest_correct"], 24);
                assert_eq!(
                    evidence["candidate_correct"],
                    if index < 2 { 23 } else { 25 }
                );
                assert_eq!(evidence["score"], if index < 2 { 0 } else { 40_000 });
                if height == 176 {
                    let evaluation = evaluation::read_evaluation(&after, cid).unwrap();
                    assert_eq!(evaluation["closed"]["status"], "complete-scored");
                    assert_eq!(evaluation["closed"]["closed_height"], 176);
                    assert_eq!(evaluation["closed"]["score"], evidence["score"]);
                    assert_eq!(object(&after, cid)["status"], "evaluated");
                }
            }
        }
        if height == 184 {
            let fixture = second.as_ref().unwrap();
            observe_release("nonzero-parent", &state, &c, fixture, 100_000, Ok(&after));
            assert_record(&after, &c, fixture, second_release, &second_models, 25, 24);
            assert_eq!(after["model:current"], hex::encode(second_release));
            assert_eq!(
                stored_model(&after, &c, fixture.bundle.candidate_artifact),
                full_model(&c, &target)
            );
            let source = read_hash(
                &object(&after, fixture.components[0].contribution_id)["model_evidence_v4"]
                    ["source"],
            );
            assert_eq!(
                after[&composition::source_key(1, source)]["reserved_units"],
                100_000
            );
        }
        if [56, 76, 128, 129, 176, 184, 204].contains(&height) {
            eprintln!(
                "v4 two-generation native height{height}: current={}",
                after["model:current"]
            );
        }
    }
    let completed = node.read_active().unwrap();
    assert_eq!(completed.0, tip);
    let second = second.unwrap();
    let record = &completed.2[&format!("release:{}", hex::encode(second_release))];
    observe_claims("nonzero-parent", &completed.2, second_release);
    assert_eq!(record["remaining"], 0);
    for allocation in &second.allocations {
        assert_eq!(record["claims"][hex::encode(allocation.cid)], 50_000);
    }
    assert!(!completed
        .2
        .contains_key(&format!("release:{}", hex::encode(first_release))));
    drop(node);
    let reopened = Node::open(directory.path(), settings, 1).unwrap();
    assert_eq!(reopened.read_active().unwrap(), completed);
    assert_record(
        &completed.2,
        &c,
        &second,
        second_release,
        &second_models,
        25,
        24,
    );
    eprintln!("v4 two-generation fixture: first21+21→24; real parent24; zero-score children23+23−parent24→25; native_packets=204");
}

#[test]
fn signed_executor_rejects_unrelated_weak_zero_marginal_and_precommitted_false_weights() {
    let directory = tempfile::tempdir().unwrap();
    let (c, settings) = context();
    let node = Node::open(directory.path(), settings, 2).unwrap();
    let initial = node.read_active().unwrap();
    let a = trained(0, 25);
    let b = trained(1, 25);
    let third = trained(2, 25);
    let strong = trained(4, 25);
    let accurate_unrelated = trained(0, 125);
    let sum = add(&a, &b);
    let triple = add(&sum, &third);
    let mut cancelling = vec![0_i16; 2 * FEATURES];
    cancelling[FEATURES - 1] = 48;
    let opposite = cancelling.iter().map(|&v| -v).collect::<Vec<_>>();
    assert_eq!(correct(&accurate_unrelated), 25);
    assert_ne!(accurate_unrelated, sum);
    assert_eq!([correct(&strong), correct(&add(&a, &strong))], [25, 24]);
    assert_eq!([correct(&third), correct(&triple)], [20, 25]);
    assert_eq!(
        [
            correct(&add(&b, &third)),
            correct(&add(&a, &third)),
            correct(&sum)
        ],
        [25, 24, 25]
    );
    // Both cancelling components have positive LOO deltas under the old rule.
    // The exact-zero subset guard must reject them despite these four gains.
    assert_eq!(add(&cancelling, &opposite), vec![0; 2 * FEATURES]);
    assert_eq!(
        [
            correct(&b),
            correct(&a),
            correct(&subtract(&sum, &cancelling)),
            correct(&subtract(&sum, &opposite))
        ],
        [23, 24, 23, 16]
    );
    let cases = [
        (
            "unrelated-accurate",
            vec![a.clone(), b.clone()],
            accurate_unrelated,
            vec![80_000, 40_000],
            "MODEL_COMPOSITION_DERIVATION",
        ),
        (
            "exact-but-weaker",
            vec![a.clone(), strong.clone()],
            add(&a, &strong),
            vec![40_000, 40_000],
            "MODEL_COMPOSITION_GAIN",
        ),
        (
            "zero-marginals",
            vec![a.clone(), b.clone(), third],
            triple,
            vec![40_000, 40_000, 40_000],
            "MODEL_COMPOSITION_MARGINAL",
        ),
        (
            "precommitted-score-as-weight",
            vec![a.clone(), b.clone()],
            sum.clone(),
            vec![200_000, 160_000],
            "MODEL_COMPOSITION_WEIGHT",
        ),
        (
            "exact-cancelling-subset",
            vec![a.clone(), b.clone(), cancelling, opposite],
            sum.clone(),
            vec![80_000, 40_000, 80_000, 360_000],
            "MODEL_COMPOSITION_REDUNDANT_SUBSET",
        ),
    ];
    for (label, components, bundle, weights, expected) in cases {
        let fixture = Fixture::new(&initial.2, &c, 0, &components, &bundle, &weights);
        let mut state = initial.2.clone();
        // Correctly signed submissions, commitments and reveals, with every
        // M06 height present. This is explicitly not another native PNW1 chain.
        for height in 1..=55 {
            let txs = match height {
                1 => fixture.submissions(&state, &c),
                16 => attestations(&state, &c, &fixture.ids(), 14),
                32 => attestations(&state, &c, &fixture.ids(), 15),
                _ => vec![],
            };
            state = step(&state, &c, height, &txs);
        }
        for cid in fixture.ids() {
            assert_eq!(
                evaluation::read_evaluation(&state, cid).unwrap()["closed"]["status"],
                "complete-scored"
            );
            assert_eq!(object(&state, cid)["status"], "evaluated");
        }
        let before = state.clone();
        let (released, tx) = fixture.release(&state, &c, 1000);
        let error = pon_executor::execute(
            &state,
            std::slice::from_ref(&tx),
            56,
            development_public(3).unwrap(),
            [4; 32],
            4,
            &c,
        )
        .err()
        .unwrap();
        assert_eq!(error, expected, "{label}");
        observe_release(label, &state, &c, &fixture, 1000, Err(error));
        // The actual executor refusal also retains an exact diagnostic identity
        // at the Node conversion boundary without stopping its durable owner.
        let node_error = trnm_pon_node::Error::from(error);
        assert!(node_error.code().is_some(), "{label}");
        assert!(!node_error.requires_owner_stop(), "{label}");
        assert_eq!(node_error.to_string(), expected, "{label}");
        assert_eq!(state, before);
        assert!(!state.contains_key(&format!("release:{}", hex::encode(released))));
        assert_eq!(state["model:current"], initial.2["model:current"]);
        assert!(state
            .iter()
            .filter(|(key, _)| key.starts_with("model-source-v4:"))
            .all(|(_, value)| value["reserved_units"] == 0));
        rejected_prefix_keeps_prior_transaction(&state, &c, 56, tx.clone(), expected);
        if label == "precommitted-score-as-weight" {
            // The bundle was admitted with this malicious allocation root. The
            // refusal is an objective ablation-weight mismatch, not a root typo.
            assert_eq!(
                object(&state, fixture.bundle.contribution_id)["components_root"],
                hex::encode(allocation_root(&fixture.allocations))
            );
            let valid = Envelope::decode(&tx).unwrap();
            let first = valid.payload[145..185].to_vec();
            let second = valid.payload[185..225].to_vec();
            for duplicate in [false, true] {
                let mut payload = valid.payload.clone();
                if duplicate {
                    payload[185..217].copy_from_slice(&first[..32]);
                } else {
                    payload[145..185].copy_from_slice(&second);
                    payload[185..225].copy_from_slice(&first);
                }
                let malformed = signed_noncanonical(&c, nonce(&state, 3), &payload);
                assert_eq!(
                    Envelope::decode(&malformed).unwrap_err(),
                    WireError::Noncanonical
                );
                assert_eq!(
                    pon_executor::execute(
                        &state,
                        &[malformed],
                        56,
                        development_public(3).unwrap(),
                        [4; 32],
                        4,
                        &c
                    )
                    .err(),
                    Some("ENCODING")
                );
            }
            let singleton = release(&state, &c, &fixture.bundle, 1000, &fixture.allocations[..1]).1;
            assert_eq!(
                pon_executor::execute(
                    &state,
                    &[singleton],
                    56,
                    development_public(3).unwrap(),
                    [4; 32],
                    4,
                    &c
                )
                .err(),
                Some("MODEL_COMPOSITION_COUNT")
            );
            let excessive = (0..5_u8)
                .map(|index| Allocation {
                    cid: [index; 32],
                    who: 0,
                    weight: 1,
                })
                .collect::<Vec<_>>();
            let tx = release(&state, &c, &fixture.bundle, 1000, &excessive).1;
            assert_eq!(
                pon_executor::execute(
                    &state,
                    &[tx],
                    56,
                    development_public(3).unwrap(),
                    [4; 32],
                    4,
                    &c
                )
                .err(),
                Some("MODEL_COMPOSITION_COUNT")
            );
        }
        eprintln!(
            "v4 signed M06 negative {label}: {expected}; rejected suffix preserves prior transfer"
        );
    }
    assert_eq!(node.read_active().unwrap(), initial);
}
