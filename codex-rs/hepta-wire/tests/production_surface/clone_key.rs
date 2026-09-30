use codex_hepta_wire::SessionMacKey;

fn duplicate(key: &SessionMacKey) {
    let _ = key.clone();
}

fn main() {}
