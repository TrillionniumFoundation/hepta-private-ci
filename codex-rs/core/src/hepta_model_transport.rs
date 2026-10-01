//! Optional Linux product route to the credential-owning model authority.
//! The root launcher freezes the socket in its execution digest; the service
//! independently admits the real process and lease. No credentials enter here.

use codex_http_client::HttpClient;

pub(crate) fn client(request_url: &str) -> std::io::Result<Option<HttpClient>> {
    let Some(socket) = std::env::var_os("HEPTA_MODEL_RELAY_SOCKET") else {
        return Ok(None);
    };
    #[cfg(not(target_os = "linux"))]
    {
        let _ = (socket, request_url);
        Err(std::io::Error::other(
            "model authority relay requires Linux",
        ))
    }
    #[cfg(target_os = "linux")]
    {
        client_for_socket(std::path::Path::new(&socket), request_url).map(Some)
    }
}

#[cfg(target_os = "linux")]
fn client_for_socket(socket: &std::path::Path, request_url: &str) -> std::io::Result<HttpClient> {
    use std::os::unix::fs::FileTypeExt;
    use std::os::unix::fs::MetadataExt;
    if request_url != "http://localhost/hepta/v1/responses"
        || !socket.is_absolute()
        || socket
            .components()
            .any(|part| matches!(part, std::path::Component::ParentDir))
    {
        return Err(std::io::Error::other(
            "unsupported model authority relay destination",
        ));
    }
    for parent in socket.ancestors().skip(1) {
        let metadata = std::fs::symlink_metadata(parent)?;
        if !metadata.is_dir() || metadata.uid() != 0 || metadata.mode() & 0o022 != 0 {
            return Err(std::io::Error::other(
                "model relay directory is not root protected",
            ));
        }
    }
    let metadata = std::fs::symlink_metadata(socket)?;
    if !metadata.file_type().is_socket() || metadata.uid() != 0 || metadata.mode() & 0o007 != 0 {
        return Err(std::io::Error::other(
            "model relay socket is not root protected",
        ));
    }
    let client = reqwest::Client::builder()
        .unix_socket(socket)
        .no_proxy()
        .redirect(reqwest::redirect::Policy::none())
        .build()
        .map_err(std::io::Error::other)?;
    Ok(HttpClient::new_without_request_logging(client))
}

#[cfg(all(test, target_os = "linux"))]
mod tests {
    use super::*;

    #[test]
    fn foreign_routes_and_unprotected_real_socket_cannot_fall_back_to_tcp() {
        let directory = tempfile::tempdir().unwrap();
        let socket = directory.path().join("model.sock");
        let _listener = std::os::unix::net::UnixListener::bind(&socket).unwrap();
        assert!(client_for_socket(&socket, "https://api.openai.com/v1/responses").is_err());
        assert!(client_for_socket(&socket, "http://localhost/hepta/v1/responses/compact").is_err());
        assert!(client_for_socket(&socket, "http://localhost/hepta/v1/responses").is_err());
        let alias = directory.path().join("alias.sock");
        std::os::unix::fs::symlink(&socket, &alias).unwrap();
        assert!(client_for_socket(&alias, "http://localhost/hepta/v1/responses").is_err());
    }
}
