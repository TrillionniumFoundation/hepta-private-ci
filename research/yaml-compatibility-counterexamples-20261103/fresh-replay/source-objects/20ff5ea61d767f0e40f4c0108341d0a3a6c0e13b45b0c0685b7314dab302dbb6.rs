// Reconstructed from the executed pre-reset tool command; not rerun after reset.
#![allow(dead_code)]
mod safe_yaml;
#[path="baseline/command.rs"] mod baseline_command;
#[path="candidate/command.rs"] mod candidate_command;
#[path="baseline/parser.rs"] mod baseline_parser;
#[path="candidate/parser.rs"] mod candidate_parser;
use serde_json::json;
fn main() {
 for (name,input) in [
  ("leading_zero","description: 007"),
  ("implicit_float_overflow","description: 1e999"),
  ("integer_128_range","description: 18446744073709551616"),
  ("explicit_float_overflow","description: !!float 1e999"),
  ("bool_semantic_duplicate","true: a\nTrue: b\ndescription: hi"),
  ("float_semantic_duplicate","1.0: a\n1.00: b\ndescription: hi"),
  ("integer_semantic_duplicate","0xB: a\n11: b\ndescription: hi"),
  ("signed_zero_float_duplicate","0.0: a\n-0.0: b\ndescription: hi"),
  ("nan_duplicate",".nan: a\n.NaN: b\ndescription: hi"),
  ("composite_mapping_duplicate","? {a: 1, b: 2}\n: first\n? {b: 2, a: 1}\n: second\ndescription: hi"),
  ("bool_and_string_key","true: a\n\"true\": b\ndescription: hi"),
  ("float_and_string_key","1.0: a\n\"1.0\": b\ndescription: hi"),
  ("global_scalar_tag","description: !<tag:example.org,2026:custom> 42"),
  ("binary_tag","description: !!binary aGVsbG8="),
  ("unrelated_local_int","unrelated: !int hello\ndescription: hi"),
  ("unrelated_local_null","unrelated: !null hello\ndescription: hi"),
  ("tagged_top_mapping","!root {description: hi}"),
  ("tagged_description_key","!key description: hi"),
  ("core_sequence_tag_on_scalar","description: !!seq hi"),
  ("core_int_tag_on_sequence","unrelated: !!int [one]\ndescription: hi"),
 ] {
  let old=baseline_command::parse_command_description(input);
  let new=candidate_command::parse_command_description(input);
  println!("{}",json!({"consumer":"command_description","name":name,"input":input,"baseline":old,"candidate":new,"equal":old==new}));
 }
 for (name,input) in [
  ("local_null_text","name: demo\ndescription: !null hello"),
  ("local_int_text","name: demo\ndescription: !int hello"),
  ("global_int_text","name: demo\ndescription: !!int hello"),
  ("local_str_null","name: demo\ndescription: !str null"),
  ("global_null_text","name: demo\ndescription: !!null hello"),
  ("global_null_quoted","name: demo\ndescription: !!null 'hello'"),
  ("global_bool_text","name: demo\ndescription: !!bool hello"),
  ("named_metadata_with_tag","name: demo\ndescription: hi\nmetadata: !!str {short-description: note}"),
 ] {
  let document=format!("---\n{input}\n---\nBody");
  let old=baseline_parser::parse_skill_frontmatter_metadata(&document,||"fallback".to_owned())
     .map(|x|(x.name,x.description,x.short_description)).ok();
  let new=candidate_parser::parse_skill_frontmatter_metadata(&document,||"fallback".to_owned())
     .map(|x|(x.name,x.description,x.short_description)).ok();
  println!("{}",json!({"consumer":"skill_frontmatter","name":name,"input":document,"baseline":old,"candidate":new,"equal":old==new}));
 }
}
