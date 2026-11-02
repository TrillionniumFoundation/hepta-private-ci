use crate::policy;
use crate::task;

#[test]
fn numpy_and_torch_golden_conditional_states_match_all_three_rust_families() {
    let directory = std::path::PathBuf::from(std::env::var("HEPTA_JOINT_GOLDEN_DIR").unwrap());
    let golden: serde_json::Value =
        serde_json::from_slice(&std::fs::read(directory.join("states.json")).unwrap()).unwrap();
    let public: task::Public = serde_json::from_value(golden["public"].clone()).unwrap();
    public.validate().unwrap();
    for family in ["renewal", "full_markov", "gru"] {
        let model: policy::Policy = serde_json::from_slice(
            &std::fs::read(directory.join(format!("{family}.json"))).unwrap(),
        )
        .unwrap();
        model.validate(&public).unwrap();
        for row in golden["predictions"]
            .as_array()
            .unwrap()
            .iter()
            .filter(|r| r["family"] == family)
        {
            let i = row["state_index"].as_u64().unwrap() as usize;
            let state: task::State = serde_json::from_value(golden["states"][i].clone()).unwrap();
            let actual = serde_json::to_value(model.predict(&public, &state).unwrap()).unwrap();
            for name in ["q", "mass", "bank"] {
                let a = actual[name].as_array().unwrap();
                let b = row["prediction"][name].as_array().unwrap();
                assert_eq!(a.len(), b.len());
                for (a, b) in a.iter().zip(b) {
                    assert!((a.as_f64().unwrap() - b.as_f64().unwrap()).abs() < 5e-12);
                }
            }
            for name in ["belief", "logit"] {
                assert!(
                    (actual[name].as_f64().unwrap() - row["prediction"][name].as_f64().unwrap())
                        .abs()
                        < 5e-12
                );
            }
        }
    }
}
