use hepta_native::session_store::GatewayCredentialStore;

fn main() {
    if let Err(error) = run() {
        eprintln!("hepta-native-credential: {error}");
        std::process::exit(1);
    }
}

fn run() -> Result<(), Box<dyn std::error::Error>> {
    let mut args = std::env::args().skip(1);
    let command = args.next().ok_or("missing command: provision | delete")?;
    let account = args.next().ok_or("missing keyring account")?;
    if args.next().is_some() {
        return Err("unexpected credential arguments".into());
    }
    let store = GatewayCredentialStore::default();
    match command.as_str() {
        "provision" => {
            let receipt = store.provision_random(&account)?;
            println!(
                "{{\"schema\":\"hepta.native-gateway-credential-provision.v1\",\"account\":{},\"token_digest\":{}}}",
                serde_json::to_string(&receipt.account)?,
                serde_json::to_string(&receipt.token_digest)?
            );
        }
        "delete" => {
            let deleted = store.delete(&account)?;
            println!(
                "{{\"schema\":\"hepta.native-gateway-credential-delete.v1\",\"account\":{},\"deleted\":{deleted}}}",
                serde_json::to_string(&account)?
            );
        }
        _ => return Err("unknown command: expected provision | delete".into()),
    }
    Ok(())
}
