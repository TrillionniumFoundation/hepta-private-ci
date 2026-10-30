use std::collections::BTreeMap;
use std::collections::BTreeSet;

use super::*;

fn action(name: &str, successor: &str, cost: f64) -> SngrActionShadowV1 {
    SngrActionShadowV1 {
        name: name.to_owned(),
        successor: successor.to_owned(),
        compute_cost: cost,
        task_reward: 0.0,
    }
}

fn chance(successor: &str, probability: f64) -> SngrChanceShadowV1 {
    SngrChanceShadowV1 {
        successor: successor.to_owned(),
        probability,
    }
}

fn terminal(utility: f64) -> SngrGraphNodeShadowV1 {
    SngrGraphNodeShadowV1::Terminal { utility }
}

fn test_graph() -> SngrGraphShadowV1 {
    SngrGraphShadowV1 {
        root: "root".to_owned(),
        nodes: BTreeMap::from([
            (
                "root".to_owned(),
                SngrGraphNodeShadowV1::Decision {
                    actions: vec![
                        action("guess", "guess", /*cost*/ 0.0),
                        action("inspect", "chance", /*cost*/ 0.5),
                    ],
                },
            ),
            ("guess".to_owned(), terminal(1.0)),
            (
                "chance".to_owned(),
                SngrGraphNodeShadowV1::Chance {
                    outcomes: vec![
                        chance("good", /*probability*/ 0.5),
                        chance("bad", /*probability*/ 0.5),
                    ],
                },
            ),
            ("good".to_owned(), terminal(5.0)),
            ("bad".to_owned(), terminal(1.0)),
        ]),
        legal_actions: BTreeSet::from(["guess".to_owned(), "inspect".to_owned()]),
    }
}

#[test]
fn maximize_legal_controls_but_integrate_chance() {
    let result = evaluate_sngr_graph_shadow(&test_graph()).expect("valid graph");
    assert!((result.root_utility - 2.5).abs() < 1e-12);
    assert_eq!(result.selected_actions["root"], "inspect");
    assert_eq!(result.authority, AuthorityPosture::DENY_ALL);
    assert_eq!(result.unique_evaluated_nodes, 5);
}

#[test]
fn mask_and_order_do_not_allow_illegal_policies() {
    let mut graph = test_graph();
    graph.legal_actions = BTreeSet::from(["guess".to_owned()]);
    let selected = evaluate_sngr_graph_shadow(&graph).expect("legal branch");
    assert_eq!(selected.selected_actions["root"], "guess");
    assert_eq!(selected.unique_evaluated_nodes, 2);
    graph.legal_actions.clear();
    assert_eq!(
        evaluate_sngr_graph_shadow(&graph),
        Err(SngrGraphShadowError::NoLegalAction)
    );
}

#[test]
fn tie_breaks_by_name_even_when_edge_order_reverses() {
    let mut graph = SngrGraphShadowV1 {
        root: "root".to_owned(),
        nodes: BTreeMap::from([
            (
                "root".to_owned(),
                SngrGraphNodeShadowV1::Decision {
                    actions: vec![
                        action("b", "b", /*cost*/ 0.0),
                        action("a", "a", /*cost*/ 0.0),
                    ],
                },
            ),
            ("a".to_owned(), terminal(2.0)),
            ("b".to_owned(), terminal(2.0)),
        ]),
        legal_actions: BTreeSet::from(["a".to_owned(), "b".to_owned()]),
    };
    let a = evaluate_sngr_graph_shadow(&graph).expect("tie baseline");
    assert_eq!(a.selected_actions["root"], "a");
    if let Some(SngrGraphNodeShadowV1::Decision { actions }) = graph.nodes.get_mut("root") {
        actions.reverse();
    }
    let b = evaluate_sngr_graph_shadow(&graph).expect("reversed edge order");
    assert_eq!(b.selected_actions["root"], "a");
}

#[test]
fn exact_dag_sharing_memoizes_one_descendant() {
    let graph = SngrGraphShadowV1 {
        root: "root".to_owned(),
        nodes: BTreeMap::from([
            (
                "root".to_owned(),
                SngrGraphNodeShadowV1::Chance {
                    outcomes: vec![
                        chance("left", /*probability*/ 0.5),
                        chance("right", /*probability*/ 0.5),
                    ],
                },
            ),
            (
                "left".to_owned(),
                SngrGraphNodeShadowV1::Decision {
                    actions: vec![action("a", "shared", /*cost*/ 0.2)],
                },
            ),
            (
                "right".to_owned(),
                SngrGraphNodeShadowV1::Decision {
                    actions: vec![action("a", "shared", /*cost*/ 0.4)],
                },
            ),
            ("shared".to_owned(), terminal(3.0)),
        ]),
        legal_actions: BTreeSet::from(["a".to_owned()]),
    };
    let result = evaluate_sngr_graph_shadow(&graph).expect("shared child");
    assert_eq!(result.unique_evaluated_nodes, 4);
    assert_eq!(result.memoized_references, 1);
    assert!((result.root_utility - 2.7).abs() < 1e-12);
}

#[test]
fn rejects_malformed_chance_even_for_zero_probability_missing_target() {
    for invalid in [
        vec![
            chance("good", /*probability*/ 0.3),
            chance("bad", /*probability*/ 0.3),
        ],
        vec![
            chance("good", /*probability*/ -0.1),
            chance("bad", /*probability*/ 1.1),
        ],
        vec![chance("good", f64::NAN), chance("bad", /*probability*/ 1.0)],
        vec![
            chance("good", /*probability*/ 1.0),
            chance("missing", /*probability*/ 0.0),
        ],
    ] {
        let mut graph = test_graph();
        graph.nodes.insert(
            "chance".to_owned(),
            SngrGraphNodeShadowV1::Chance { outcomes: invalid },
        );
        assert!(evaluate_sngr_graph_shadow(&graph).is_err());
    }
}

#[test]
fn rejects_cycle_even_through_ignored_branch() {
    let mut graph = test_graph();
    graph.nodes.insert(
        "bad".to_owned(),
        SngrGraphNodeShadowV1::Decision {
            actions: vec![action("cycle", "root", /*cost*/ 0.0)],
        },
    );
    graph.legal_actions.remove("cycle");
    assert_eq!(
        evaluate_sngr_graph_shadow(&graph),
        Err(SngrGraphShadowError::Cycle)
    );
}

#[test]
fn malformed_illegal_actions_are_rejected_before_scoring() {
    let mut graph = test_graph();
    graph.legal_actions.remove("inspect");
    if let Some(SngrGraphNodeShadowV1::Decision { actions }) = graph.nodes.get_mut("root") {
        actions[1].compute_cost = -1.0;
    }
    assert_eq!(
        evaluate_sngr_graph_shadow(&graph),
        Err(SngrGraphShadowError::InvalidCost)
    );
    let mut dup = test_graph();
    if let Some(SngrGraphNodeShadowV1::Decision { actions }) = dup.nodes.get_mut("root") {
        actions[1].name = "guess".to_owned();
    }
    assert_eq!(
        evaluate_sngr_graph_shadow(&dup),
        Err(SngrGraphShadowError::DuplicateAction)
    );
}

#[test]
fn reject_missing_root_broken_edges_and_node_limit() {
    let mut graph = test_graph();
    graph.root = "missing".to_owned();
    assert_eq!(
        evaluate_sngr_graph_shadow(&graph),
        Err(SngrGraphShadowError::MissingRoot)
    );
    let mut graph = test_graph();
    graph.nodes.remove("bad");
    assert_eq!(
        evaluate_sngr_graph_shadow(&graph),
        Err(SngrGraphShadowError::MissingSuccessor)
    );
    let mut graph = test_graph();
    for i in 0..257 {
        graph.nodes.insert(format!("extra-{i}"), terminal(0.0));
    }
    assert_eq!(
        evaluate_sngr_graph_shadow(&graph),
        Err(SngrGraphShadowError::GraphSize)
    );
}

#[test]
fn receipts_are_deterministic_data_only_and_bind_policy_revision() {
    let mut graph = test_graph();
    let receipt = evaluate_sngr_graph_shadow(&graph).expect("graph receipt");
    assert_eq!(receipt, evaluate_sngr_graph_shadow(&graph).expect("replay"));
    assert_ne!(receipt.evidence_digest, Digest32::ZERO);
    assert_eq!(receipt.authority, AuthorityPosture::DENY_ALL);
    graph.legal_actions.remove("inspect");
    let changed = evaluate_sngr_graph_shadow(&graph).expect("valid different policy");
    assert_ne!(changed.evidence_digest, receipt.evidence_digest);
}

#[test]
fn value_graph_depth_is_explicitly_bounded() {
    let mut nodes = BTreeMap::new();
    for i in 0..67 {
        let next = i + 1;
        let node = if i == 66 {
            terminal(1.0)
        } else {
            SngrGraphNodeShadowV1::Chance {
                outcomes: vec![chance(&format!("node-{next}"), /*probability*/ 1.0)],
            }
        };
        nodes.insert(format!("node-{i}"), node);
    }
    let graph = SngrGraphShadowV1 {
        root: "node-0".to_owned(),
        nodes,
        legal_actions: BTreeSet::new(),
    };
    assert_eq!(
        evaluate_sngr_graph_shadow(&graph),
        Err(SngrGraphShadowError::Depth)
    );
}
