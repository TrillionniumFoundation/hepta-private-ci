// Reconstructed from the executed pre-reset tool command; not rerun after reset.
use serde_saphyr::{Tagged,Options,from_str_with_options};
fn options(enabled:bool)->Options {
 serde_saphyr::options!{preserve_local_application_tags:enabled, strict_booleans:true,
  merge_keys:serde_saphyr::MergeKeyPolicy::AsOrdinary,
  duplicate_keys:serde_saphyr::DuplicateKeyPolicy::PassThrough,
  ignore_binary_tag_for_string:true}
}
#[test] fn local_int_text_is_an_application_tag(){
 assert!(from_str_with_options::<Tagged<String>>("!int hello",options(false)).is_err());
 let x=from_str_with_options::<Tagged<String>>("!int hello",options(true)).unwrap();
 assert_eq!(x,Tagged("hello".to_owned(),Some("!int".to_owned())));
}
#[test] fn global_core_and_directive_core_stay_core(){
 for text in ["!!int hello","!<tag:yaml.org,2002:int> hello","%TAG !c! tag:yaml.org,2002:\n--- !c!int hello"] {
  for enabled in [false,true] {assert!(from_str_with_options::<Tagged<String>>(text,options(enabled)).is_err());}
 }
}
#[test] fn local_tag_alias_preserves_definition_and_tag(){
 use std::collections::BTreeMap;
 let doc=from_str_with_options::<BTreeMap<String,Tagged<String>>>("source: &a !int hello\ncopy: *a",options(true)).unwrap();
 assert_eq!(doc["source"],doc["copy"]);
 assert_eq!(doc["copy"].1.as_deref(),Some("!int"));
}
#[test] fn nonspecific_and_unknown_global_tags_are_unchanged(){
 for text in ["! 42","!<tag:example.org,2026:unknown> hello"] {
  let a=from_str_with_options::<Tagged<String>>(text,options(false)).unwrap();
  let b=from_str_with_options::<Tagged<String>>(text,options(true)).unwrap();
  assert_eq!(a,b);
 }
}
#[test] fn default_alias_and_budget_configuration_unchanged(){
 let a=options(false);let b=options(true);
 assert_eq!(format!("{:?}",a.budget),format!("{:?}",b.budget));
 assert_eq!(format!("{:?}",a.alias_limits),format!("{:?}",b.alias_limits));
}
#[test] fn alias_replay_limit_is_still_enforced(){
 for enabled in [false,true]{
  let mut o=options(enabled);o.alias_limits.max_total_replayed_events=2;
  let e=from_str_with_options::<serde_json::Value>("a: &a text\nb: *a\nc: *a\nd: *a",o).unwrap_err();
  assert!(e.to_string().contains("alias replay limit exceeded"),"{e}");
 }
}
#[test] fn container_depth_limit_is_still_enforced(){
 for enabled in [false,true]{
  let mut o=options(enabled);o.budget.as_mut().unwrap().max_depth=2;
  let e=from_str_with_options::<serde_json::Value>("[[[[text]]]]",o).unwrap_err();
  assert!(e.to_string().contains("depth"),"{e}");
 }
}
