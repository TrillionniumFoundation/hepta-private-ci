#![allow(dead_code)]
mod safe_yaml;
fn main() {
    let mut args = std::env::args().skip(1);
    let variant = args.next().unwrap();
    let depth = args.next().unwrap().parse::<usize>().unwrap();
    let shape = args.next().unwrap_or_else(|| "sequence".to_owned());
    let (open, close) = match shape.as_str() {
        "sequence" => ("[", "]"), "tagged-sequence" => ("!local [", "]"),
        "mapping" => ("{x: ", "}"), "tagged-mapping" => ("!local {x: ", "}"),
        _ => panic!("unknown shape"),
    };
    let input = format!("{}x{}", open.repeat(depth), close.repeat(depth));
    let handle = std::thread::Builder::new().name(format!("{variant}-{depth}")).spawn(move || {
        let result = match variant.as_str() {
            "legacy" => serde_yaml::from_str::<serde_yaml::Value>(&input).map(|_| ()).map_err(|e| e.to_string()),
            "official-json" => serde_saphyr_official::from_str::<serde_json::Value>(&input).map(|_| ()).map_err(|e| e.to_string()),
            "fork-default-json" => serde_saphyr::from_str::<serde_json::Value>(&input).map(|_| ()).map_err(|e| e.to_string()),
            "fork-default-value" => serde_saphyr::from_str::<safe_yaml::Value>(&input).map(|_| ()).map_err(|e| e.to_string()),
            "fork-active-value" => safe_yaml::from_str::<safe_yaml::Value>(&input).map(|_| ()).map_err(|e| e.to_string()),
            _ => panic!("unknown variant"),
        };
        println!("{result:?}");
    }).unwrap();
    handle.join().unwrap();
}
