use codex_utils_absolute_path::AbsolutePathBuf;
use serde_json::Value;
use serde_json::json;
use sqlx::sqlite::SqliteConnectOptions;
use sqlx::sqlite::SqliteJournalMode;
use sqlx::sqlite::SqlitePoolOptions;
use std::path::Path;
use std::path::PathBuf;

fn acl(path: &Path) -> Result<Value, Box<dyn std::error::Error>> {
    if !path.try_exists()? {
        return Ok(json!({"exists": false}));
    }
    let shell = PathBuf::from(
        std::env::var_os("HEPTA_PROBE_POWERSHELL").ok_or("actual parent PowerShell missing")?,
    );
    let code = r#"$ErrorActionPreference='Stop'; $a=Get-Acl -LiteralPath $env:HEPTA_SQLITE_PROBE_FILE; $rules=@($a.GetAccessRules($true,$true,[System.Security.Principal.SecurityIdentifier]) | ForEach-Object { [ordered]@{sid=$_.IdentityReference.Value;mask=[int]$_.FileSystemRights;type=$_.AccessControlType.ToString();inherited=$_.IsInherited} }); [ordered]@{exists=$true;owner=$a.GetOwner([System.Security.Principal.SecurityIdentifier]).Value;protected=$a.AreAccessRulesProtected;rules=$rules} | ConvertTo-Json -Depth 8 -Compress"#;
    let output = std::process::Command::new(shell)
        .args(["-NoProfile", "-NonInteractive", "-Command", code])
        .env("HEPTA_SQLITE_PROBE_FILE", path)
        .output()?;
    if !output.status.success() {
        return Err(String::from_utf8_lossy(&output.stderr).into_owned().into());
    }
    Ok(serde_json::from_slice(&output.stdout)?)
}

#[tokio::main(flavor = "current_thread")]
async fn main() -> Result<(), Box<dyn std::error::Error>> {
    let root = PathBuf::from(std::env::args_os().nth(1).ok_or("probe root missing")?);
    drop(codex_utils_path::open_private_state_directory(&root)?);
    let canonical = root.canonicalize()?;
    let normalized = AbsolutePathBuf::try_from(canonical.clone())?;
    let source = canonical.join("actual-sqlx.sqlite3");
    let candidate = canonical.join("candidate.sqlite3");
    eprintln!(
        "PATH_NORMALIZATION_FACTS={}",
        json!({
            "osCanonicalHome": canonical,
            "normalizedAbsoluteHome": normalized.as_path(),
            "sourceParentEqualsNormalizedHome": source.parent() == Some(normalized.as_path()),
            "candidateParentEqualsNormalizedHome": candidate.parent() == Some(normalized.as_path()),
            "authorityGranted": false,
        })
    );
    let pool = SqlitePoolOptions::new()
        .max_connections(1)
        .connect_with(
            SqliteConnectOptions::new()
                .filename(&source)
                .create_if_missing(true)
                .journal_mode(SqliteJournalMode::Wal),
        )
        .await?;
    sqlx::query("CREATE TABLE actual_probe (value TEXT NOT NULL)")
        .execute(&pool)
        .await?;
    sqlx::query("INSERT INTO actual_probe VALUES ('original bytes')")
        .execute(&pool)
        .await?;
    let sqlite_version: String = sqlx::query_scalar("SELECT sqlite_version()")
        .fetch_one(&pool)
        .await?;
    let journal: String = sqlx::query_scalar("PRAGMA journal_mode")
        .fetch_one(&pool)
        .await?;
    let paths = ["", "-wal", "-shm", "-journal"]
        .map(|suffix| PathBuf::from(format!("{}{suffix}", source.display())));
    let live: Vec<_> = paths
        .iter()
        .map(|path| acl(path))
        .collect::<Result<_, _>>()?;
    pool.close().await;
    let closed: Vec<_> = paths
        .iter()
        .map(|path| acl(path))
        .collect::<Result<_, _>>()?;
    println!(
        "{}",
        serde_json::to_string_pretty(&json!({
            "schema": "hepta.windows-original-utility-sqlx-facts.v1",
            "status": "OBSERVATION_ONLY",
            "osCanonicalHome": canonical,
            "normalizedAbsoluteHome": normalized.as_path(),
            "sourcePath": source,
            "sourceParentEqualsNormalizedHome": source.parent() == Some(normalized.as_path()),
            "candidateParentEqualsNormalizedHome": candidate.parent() == Some(normalized.as_path()),
            "journalModeObserved": journal,
        "sqliteEngineVersionObserved": sqlite_version,
            "filePaths": paths,
            "homeSecurity": acl(&root)?,
            "liveSqlxSecurity": live,
            "closedSqlxSecurity": closed,
            "productionAuthorityGranted": false,
            "nativeBackendQualification": false,
            "finalProductQualification": false,
        }))?
    );
    Ok(())
}
