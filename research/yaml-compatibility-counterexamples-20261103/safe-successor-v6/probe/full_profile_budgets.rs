// Exercise resource controls with every compatibility option active.
// The inactive profile is the negative-control configuration of the same fork.
mod safe_yaml;
use safe_yaml::Value;
use serde_saphyr::{Options, from_str_with_options};

fn profile(active: bool) -> Options {
    serde_saphyr::options! {
        merge_keys: serde_saphyr::MergeKeyPolicy::AsOrdinary,
        strict_booleans: true,
        duplicate_keys: serde_saphyr::DuplicateKeyPolicy::PassThrough,
        ignore_binary_tag_for_string: true,
        preserve_local_application_tags: active,
        legacy_string_semantics: active,
        legacy_serde_yaml_scalars: active,
        legacy_serde_yaml_node_tags: active,
    }
}

fn reject(input: &str, options: Options, expected: &str) {
    let error = from_str_with_options::<Value>(input, options).unwrap_err();
    assert!(error.to_string().contains(expected), "{error}");
}

#[test]
fn all_resource_options_remain_default() {
    let official = Options::default();
    let compatibility = profile(true);
    assert_eq!(format!("{:?}", official.budget), format!("{:?}", compatibility.budget));
    assert_eq!(format!("{:?}", official.alias_limits), format!("{:?}", compatibility.alias_limits));
}

#[test]
fn nesting_and_flow_limits() {
    for active in [false, true] {
        let mut options = profile(active);
        options.budget.as_mut().unwrap().max_depth = 2;
        reject("[[[[x]]]]", options, "depth");
        let mut options = profile(active);
        options.budget.as_mut().unwrap().flow_nesting_limit = 2;
        reject("[[[[x]]]]", options, "recursion limit exceeded");
    }
}

#[test]
fn default_depth_boundary_is_enforced() {
    for active in [false, true] {
        let allowed = format!("{}x{}", "[".repeat(64), "]".repeat(64));
        from_str_with_options::<Value>(&allowed, profile(active)).unwrap();
        let denied = format!("{}x{}", "[".repeat(65), "]".repeat(65));
        reject(&denied, profile(active), "depth");
    }
}

#[test]
fn nodes_and_events() {
    for active in [false, true] {
        let mut options = profile(active);
        options.budget.as_mut().unwrap().max_nodes = 2;
        reject("[a,b,c]", options, "nodes");
        let mut options = profile(active);
        options.budget.as_mut().unwrap().max_events = 2;
        reject("[a,b,c]", options, "events");
    }
}

#[test]
fn scalar_bytes_and_explicit_empty_document_accounting() {
    for active in [false, true] {
        let mut options = profile(active);
        options.budget.as_mut().unwrap().max_total_scalar_bytes = 4;
        reject("hello", options, "scalar");
        // The parser's zero-span synthetic '~' stays in the event stream and
        // is still charged even when the String adapter exposes empty text.
        let mut options = profile(active);
        options.budget.as_mut().unwrap().max_total_scalar_bytes = 0;
        let error = from_str_with_options::<String>("---", options).unwrap_err();
        assert!(error.to_string().contains("scalar"), "{error}");
    }
}

#[test]
fn anchor_and_alias_counts() {
    for active in [false, true] {
        let mut options = profile(active);
        options.budget.as_mut().unwrap().max_anchors = 0;
        reject("a: &a x", options, "anchors");
        let mut options = profile(active);
        options.budget.as_mut().unwrap().max_aliases = 0;
        reject("a: &a x\nb: *a", options, "aliases");
    }
}

#[test]
fn replay_and_anchor_retention() {
    for active in [false, true] {
        let mut options = profile(active);
        options.alias_limits.max_total_replayed_events = 2;
        reject("a: &a x\nb: *a\nc: *a\nd: *a", options, "alias replay");
        let mut options = profile(active);
        options.budget.as_mut().unwrap().max_recorded_anchor_events = 0;
        reject("a: &a [x,y,z]", options, "anchor");
    }
}

#[test]
fn cyclic_and_unknown_aliases_remain_errors() {
    for active in [false, true] {
        assert!(from_str_with_options::<Value>("a: &a [*a]", profile(active)).is_err());
        assert!(from_str_with_options::<Value>("a: *missing", profile(active)).is_err());
    }
}

#[test]
fn bounded_reader_input() {
    for active in [false, true] {
        let mut options = profile(active);
        options.budget.as_mut().unwrap().max_reader_input_bytes = Some(4);
        assert!(serde_saphyr::from_reader_with_options::<_, Value>("hello".as_bytes(), options).is_err());
    }
}
