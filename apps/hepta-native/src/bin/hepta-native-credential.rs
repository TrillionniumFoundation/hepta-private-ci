use std::io::Read as _;
use zeroize::Zeroizing;

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
        "provision" | "provision-lifecycle" => {
            let receipt = if command == "provision-lifecycle" {
                store.provision_lifecycle(&account)?
            } else {
                store.provision_random(&account)?
            };
            println!(
                "{{\"schema\":\"hepta.native-gateway-credential-provision.v1\",\"account\":{},\"token_digest\":{}}}",
                serde_json::to_string(&receipt.account)?,
                serde_json::to_string(&receipt.token_digest)?
            );
        }
        "delete" | "delete-lifecycle" => {
            let deleted = if command == "delete-lifecycle" {
                store.delete_lifecycle(&account)?
            } else {
                store.delete(&account)?
            };
            println!(
                "{{\"schema\":\"hepta.native-gateway-credential-delete.v1\",\"account\":{},\"deleted\":{deleted}}}",
                serde_json::to_string(&account)?
            );
        }
        "import" | "import-lifecycle" => {
            let mut token = Zeroizing::new(String::new());
            std::io::stdin().take(257).read_to_string(&mut token)?;
            if command == "import-lifecycle" {
                store.import_lifecycle(&account, &token)?;
            } else {
                store.import_read(&account, &token)?;
            }
            println!("credential imported into the operating system keyring");
        }
        _ => return Err("unknown command: expected provision | delete".into()),
    }
    Ok(())
}
