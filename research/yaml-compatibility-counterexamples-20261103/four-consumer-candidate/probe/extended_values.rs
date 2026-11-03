#![allow(dead_code)]
mod safe_yaml;
use serde::de::DeserializeOwned;
use serde_json::{json, Value as Json};
fn old_value(v: &serde_yaml::Value) -> Json {
    use serde_yaml::Value::*;
    match v {
        Null => json!(["null"]), Bool(x) => json!(["bool", x]), String(x) => json!(["string", x]),
        Number(x) => json!(["number", if x.is_u64(){"u64"}else if x.is_i64(){"i64"}else{"f64"}, x.to_string()]),
        Sequence(xs) => json!(["sequence", xs.iter().map(old_value).collect::<Vec<_>>()]),
        Mapping(xs) => json!(["mapping", xs.iter().map(|(k,v)|json!([old_value(k),old_value(v)])).collect::<Vec<_>>()]),
        Tagged(x) => json!(["tagged",x.tag.to_string(),old_value(&x.value)]),
    }
}
fn new_value(v: &safe_yaml::Value) -> Json {
    use safe_yaml::Value::*;
    match v {
        Null => json!(["null"]), Bool(x) => json!(["bool", x]), String(x) => json!(["string", x]),
        Number(x) => json!(["number", match x {safe_yaml::Number::Unsigned(_)=>"u64",safe_yaml::Number::Negative(_)=>"i64",safe_yaml::Number::Float(_)=>"f64"},x.to_string()]),
        Sequence(xs) => json!(["sequence",xs.iter().map(new_value).collect::<Vec<_>>()]),
        Mapping(xs) => json!(["mapping",xs.iter().map(|(k,v)|json!([new_value(k),new_value(v)])).collect::<Vec<_>>()]),
        Tagged(x) => json!(["tagged",x.tag.to_string(),new_value(&x.value)]),
    }
}
fn observe(kind:&str,input:Json,old:Result<Json,String>,new:Result<Json,String>,counts:&mut [usize;2]) {
    let equal=match(&old,&new){(Ok(a),Ok(b))=>a==b,(Err(_),Err(_))=>true,_=>false};
    counts[0]+=1;counts[1]+=usize::from(!equal);
    println!("{}",json!({"kind":kind,"input":input,"baseline":old,"candidate":new,"equal":equal}));
}
fn value(input:&str,c:&mut[usize;2]){
    let old=serde_yaml::from_str::<serde_yaml::Value>(input).map(|x|old_value(&x)).map_err(|e|e.to_string());
    let new=safe_yaml::from_str::<safe_yaml::Value>(input).map(|x|new_value(&x)).map_err(|e|e.to_string());
    observe("dynamic_value",json!(input),old,new,c);
}
fn typed<T:DeserializeOwned+std::fmt::Debug>(kind:&str,input:&str,c:&mut[usize;2]){
    let old=serde_yaml::from_str::<T>(input).map(|x|json!(format!("{x:?}"))).map_err(|e|e.to_string());
    let new=safe_yaml::from_str::<T>(input).map(|x|json!(format!("{x:?}"))).map_err(|e|e.to_string());
    observe(kind,json!(input),old,new,c);
}
#[derive(Debug,serde::Deserialize)] struct Version {version:u32}
fn main(){
 let mut counts=[0,0];
 let texts=["","null","~","true","tRuE","false","yes","0","-0","+0","007","-007","+007","00.5","01e2","-0.0","1.0","1e-999","1e999",".inf","+.Inf","-.INF",".nan","+.nan","NaN","inf","1_000","0xFF_FF","0x2a","+0x2a","-0x2a","0o52","0b1010","0x+1","-0x-1","++1","+-1","-+1","4294967295","4294967296","18446744073709551615","18446744073709551616","-9223372036854775809","340282366920938463463374607431768211455","340282366920938463463374607431768211456","-170141183460469231731687303715884105728","-170141183460469231731687303715884105729","hello"];
 let tags=["","!custom ","!int ","!float ","!null ","!str ","!bool ","!!str ","!!int ","!!float ","!!null ","!!bool ","!!binary ","!!seq ","!!map ","!<tag:example.org,2026:custom> ","!<!!custom> ","! "];
 for text in texts { for tag in tags { for style in 0..5 {
  let input=match style {0=>format!("{tag}{text}"),1=>format!("{tag}'{text}'"),2=>format!("{tag}\"{text}\""),3=>format!("{tag}|-\n  {text}\n"),_=>format!("{tag}|\n  {text}\n")};
  value(&input,&mut counts);typed::<u32>("u32",&input,&mut counts);typed::<Option<String>>("Option<String>",&input,&mut counts);
 }}}
 for input in [
  "? {a: 1, b: 2}\n: first\n? {b: 2, a: 1}\n: second",
  "? [a, {x: 1, y: 2}]\n: first\n? [a, {y: 2, x: 1}]\n: second",
  "!custom 1: first\n!<!!custom> 1: second",
  "!a 1: first\n!b 1: second",
  "!a [1]: first\n!a [1]: second",
  "1: integer\n1.0: float",
  "0: first\n-0: second",
  ".nan: first\n.NaN: second",
  "seed: &a !int '001'\ncopy: *a",
  "prefix: λλ\nseed: &a !!float '1e999'\ncopy: *a",
  "seed: &a |\n  007\ncopy: *a",
  "seed: &a [x, y]\ncopy: *a",
  "? &key {x: 1, y: 2}\n: first\n? *key\n: second",
  "%TAG !e! !custom\n---\n!e! 42",
  "%TAG !e! tag:example.org,2026:\n---\n!e!custom 42",
  "a: &a [*a]", "a: *missing", "[", "a: 1\n---\nb: 2", "---\n...\n---\nvalue",
  "---", "---\n...", "# comment only\n", " \n", "!!int \"\\x31\"", "! 42",
 ] {value(input,&mut counts);}
 for input in ["", "---", "---\n...", "# comment only\n", "---\n...\n---\n- x", "---\n...\n---\na: b"] {
  typed::<String>("empty_String",input,&mut counts);
  typed::<Vec<String>>("empty_Vec<String>",input,&mut counts);
  typed::<std::collections::BTreeMap<String,String>>("empty_Map",input,&mut counts);
 }
 let plain="version: 1\n";
 let mut encodings=vec![("utf8",plain.as_bytes().to_vec()),("utf8_bom",[vec![0xef,0xbb,0xbf],plain.as_bytes().to_vec()].concat()),("invalid_utf8",vec![0xff,0xff,0xff])];
 for little in [true,false]{
  let mut b=if little{vec![0xff,0xfe]}else{vec![0xfe,0xff]};
  for unit in plain.encode_utf16(){b.extend_from_slice(&if little{unit.to_le_bytes()}else{unit.to_be_bytes()});}
  encodings.push((if little{"utf16_le"}else{"utf16_be"},b));
  let mut b=if little{vec![0xff,0xfe,0,0]}else{vec![0,0,0xfe,0xff]};
  for ch in plain.chars(){b.extend_from_slice(&if little{u32::from(ch).to_le_bytes()}else{u32::from(ch).to_be_bytes()});}
  encodings.push((if little{"utf32_le"}else{"utf32_be"},b));
 }
 for (name,input) in encodings{
  let old=serde_yaml::from_slice::<Version>(&input).map(|x|json!(x.version)).map_err(|e|e.to_string());
  let new=safe_yaml::from_slice::<Version>(&input).map(|x|json!(x.version)).map_err(|e|e.to_string());
  observe("typed_slice_encoding",json!({"name":name,"hex":input.iter().map(|x|format!("{x:02x}")).collect::<String>()}),old,new,&mut counts);
 }
 eprintln!("{}",json!({"observations":counts[0],"differences":counts[1],"migration_accepted":false}));
 if counts[1]!=0{std::process::exit(1);}
}
