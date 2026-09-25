use std::path::Path;
use std::path::PathBuf;

use rand::RngCore;
use serde::Serialize;

use crate::QualificationError;
use crate::digest::framed_digest;
use crate::digest::sha256;
use crate::durable::create_or_verify_private_directory;
use crate::durable::create_private_directory;
use crate::durable::now_millis;
use crate::durable::sync_directory;
use crate::durable::write_private_new;
use crate::request::Surface;
use crate::request::canonical_json;
use crate::request::parse_request;

const MAX_REQUEST_BYTES: usize = 64 * 1024;
const ZERO_SHA256: &str = "0000000000000000000000000000000000000000000000000000000000000000";
const ORACLE_COMMIT: &str = "2f704dc7c1172cefca908852456beccf4d02a5d1";
const ORACLE_TREE: &str = "7be9a382b2610790838eef874cb4d381b5025490";
const ORACLE_CORPUS_SHA256: &str =
    "dfe4f04d26895a6fabfb8435b77d7e807f57379fbb8d2a96c85af747e996cda7";
const RUN_ID_DOMAIN: &[u8] = b"hepta-live-product-shadow-run-id:v2";
const RUN_BINDING_DOMAIN: &[u8] = b"hepta-live-product-shadow-run-binding:v2";
const SEGMENT_ID_DOMAIN: &[u8] = b"hepta-live-product-shadow-segment-id:v2";
const INTENT_ID_DOMAIN: &[u8] = b"hepta-live-product-shadow-intent-id:v2";
const INTENT_CHAIN_DOMAIN: &[u8] = b"hepta-live-product-shadow-intent-chain:v2";
const PRE_SEND_ARTIFACT_DOMAIN: &[u8] = b"hepta-live-product-shadow-driver-pre-send-artifact:v2";
const ALLOW_SEND_TOKEN_DOMAIN: &[u8] = b"hepta-live-product-shadow-allow-send-token:v2";

#[derive(Clone, Debug, Eq, PartialEq)]
pub struct DurablePreSendToken {
    run_id: String,
    surface: Surface,
    ordinal: u8,
    token_sha256: String,
}

impl DurablePreSendToken {
    pub fn run_id(&self) -> &str {
        &self.run_id
    }

    pub fn surface(&self) -> Surface {
        self.surface
    }

    pub fn ordinal(&self) -> u8 {
        self.ordinal
    }

    pub fn token_sha256(&self) -> &str {
        &self.token_sha256
    }
}

#[derive(Debug)]
pub struct CompletedPreSend {
    expected_work_directory: String,
    run_id: String,
    run_root: PathBuf,
    tokens: Vec<DurablePreSendToken>,
}

impl CompletedPreSend {
    pub fn run_id(&self) -> &str {
        &self.run_id
    }

    pub fn run_root(&self) -> &Path {
        &self.run_root
    }

    pub fn token_count(&self) -> usize {
        self.tokens.len()
    }

    pub(crate) fn expected_work_directory(&self) -> &str {
        &self.expected_work_directory
    }

    pub(crate) fn token(&self, surface: Surface, ordinal: u8) -> Option<&DurablePreSendToken> {
        self.tokens
            .iter()
            .find(|token| token.surface == surface && token.ordinal == ordinal)
    }
}

#[derive(Debug)]
enum Stage {
    AppServer { next_ordinal: u8, previous: String },
    Mcp { next_ordinal: u8, previous: String },
    Complete,
}

#[derive(Debug)]
pub struct DurablePreSendObserver {
    run_id: String,
    run_binding_sha256: String,
    run_root: PathBuf,
    expected_work_directory: String,
    stage: Stage,
    tokens: Vec<DurablePreSendToken>,
}

#[derive(Serialize)]
struct RunManifest<'a> {
    authority: bool,
    enforce: bool,
    expected_work_directory_sha256: &'a str,
    oracle_commit: &'static str,
    oracle_corpus_sha256: &'static str,
    oracle_tree: &'static str,
    outbound: bool,
    promotion: bool,
    run_binding_sha256: &'a str,
    run_id: &'a str,
    schema: &'static str,
    schema_version: u32,
}

#[derive(Serialize)]
struct ArtifactReceipt<'a> {
    allow_send_token_sha256: &'a str,
    artifact_binding_sha256: &'a str,
    authority: bool,
    durability_scope: &'static str,
    enforce: bool,
    intent_chain_sha256: &'a str,
    intent_id: &'a str,
    ordinal: u8,
    outbound: bool,
    product_http_pre_send_claimed: bool,
    promotion: bool,
    provider_semantic_sha256: &'a str,
    raw_path_sha256: &'a str,
    raw_request_body_sha256: &'a str,
    raw_request_size_bytes: usize,
    raw_request_wire_sha256: &'a str,
    run_id: &'a str,
    sample_token_sha256: &'a str,
    schema: &'static str,
    schema_version: u32,
    surface: Surface,
}

impl DurablePreSendObserver {
    pub fn create(
        root: impl AsRef<Path>,
        expected_work_directory: impl AsRef<Path>,
    ) -> Result<Self, QualificationError> {
        let root = root.as_ref();
        let expected_work_directory = expected_work_directory.as_ref();
        if !root.is_absolute() || !expected_work_directory.is_absolute() {
            return Err(invalid("observer paths must be absolute"));
        }
        create_or_verify_private_directory(root)?;
        let started_at_ms = now_millis()?;
        let mut nonce = [0_u8; 32];
        rand::rng().fill_bytes(&mut nonce);
        let started = started_at_ms.to_string();
        let run_id = framed_digest(RUN_ID_DOMAIN, [nonce.as_slice(), started.as_bytes()]);
        let run_binding_sha256 = framed_digest(
            RUN_BINDING_DOMAIN,
            [
                run_id.as_bytes(),
                ORACLE_COMMIT.as_bytes(),
                ORACLE_TREE.as_bytes(),
                ORACLE_CORPUS_SHA256.as_bytes(),
            ],
        );
        let run_root = root.join(&run_id);
        create_private_directory(&run_root)?;
        sync_directory(root)?;
        let expected_work_directory = expected_work_directory.to_string_lossy().into_owned();
        let expected_work_directory_sha256 = sha256(expected_work_directory.as_bytes());
        let manifest = RunManifest {
            authority: false,
            enforce: false,
            expected_work_directory_sha256: &expected_work_directory_sha256,
            oracle_commit: ORACLE_COMMIT,
            oracle_corpus_sha256: ORACLE_CORPUS_SHA256,
            oracle_tree: ORACLE_TREE,
            outbound: false,
            promotion: false,
            run_binding_sha256: &run_binding_sha256,
            run_id: &run_id,
            schema: "hepta_shadow_qualification_observer_run_v2",
            schema_version: 2,
        };
        write_private_new(&run_root.join("run.json"), &canonical_json(&manifest)?)?;
        Ok(Self {
            run_id,
            run_binding_sha256,
            run_root,
            expected_work_directory,
            stage: Stage::AppServer {
                next_ordinal: 1,
                previous: ZERO_SHA256.to_string(),
            },
            tokens: Vec::with_capacity(4),
        })
    }

    pub(crate) fn run_id(&self) -> &str {
        &self.run_id
    }

    pub(crate) fn run_root(&self) -> &Path {
        &self.run_root
    }

    pub fn record_app_server(
        &mut self,
        raw_request: &[u8],
    ) -> Result<DurablePreSendToken, QualificationError> {
        self.record(Surface::AppServer, raw_request)
    }

    pub fn record_mcp(
        &mut self,
        raw_request: &[u8],
    ) -> Result<DurablePreSendToken, QualificationError> {
        self.record(Surface::Mcp, raw_request)
    }

    pub fn finish(self) -> Result<CompletedPreSend, QualificationError> {
        if !matches!(self.stage, Stage::Complete) || self.tokens.len() != 4 {
            return Err(state(
                "observer requires exactly two app-server and two MCP requests",
            ));
        }
        sync_directory(&self.run_root)?;
        Ok(CompletedPreSend {
            expected_work_directory: self.expected_work_directory,
            run_id: self.run_id,
            run_root: self.run_root,
            tokens: self.tokens,
        })
    }

    fn record(
        &mut self,
        surface: Surface,
        raw_request: &[u8],
    ) -> Result<DurablePreSendToken, QualificationError> {
        if raw_request.len() > MAX_REQUEST_BYTES {
            return Err(invalid("driver request exceeds the 64 KiB bound"));
        }
        let (ordinal, previous) = match (&self.stage, surface) {
            (
                Stage::AppServer {
                    next_ordinal,
                    previous,
                },
                Surface::AppServer,
            )
            | (
                Stage::Mcp {
                    next_ordinal,
                    previous,
                },
                Surface::Mcp,
            ) if *next_ordinal <= 2 => (*next_ordinal, previous.clone()),
            _ => {
                return Err(state(
                    "driver requests must follow app_server[1..2] then mcp[1..2]",
                ));
            }
        };
        let parsed = parse_request(surface, ordinal, raw_request, &self.expected_work_directory)?;
        let segment_id = framed_digest(
            SEGMENT_ID_DOMAIN,
            [self.run_id.as_bytes(), surface.as_str().as_bytes()],
        );
        let ordinal_text = ordinal.to_string();
        let intent_id = framed_digest(
            INTENT_ID_DOMAIN,
            [
                segment_id.as_bytes(),
                ordinal_text.as_bytes(),
                parsed.sample_token_sha256.as_bytes(),
            ],
        );
        let chain = framed_digest(
            INTENT_CHAIN_DOMAIN,
            [
                previous.as_bytes(),
                intent_id.as_bytes(),
                parsed.provider_semantic_sha256.as_bytes(),
            ],
        );
        let stem = format!("{}-{ordinal:02}", surface.as_str());
        let raw_path = self.run_root.join(format!("{stem}.raw.json"));
        let receipt_path = self.run_root.join(format!("{stem}.pre-send.json"));
        let raw_path_sha256 = sha256(raw_path.to_string_lossy().as_bytes());
        let raw_wire_sha256 = sha256(raw_request);
        let raw_size = raw_request.len().to_string();
        let artifact_binding_sha256 = framed_digest(
            PRE_SEND_ARTIFACT_DOMAIN,
            [
                intent_id.as_bytes(),
                self.run_id.as_bytes(),
                segment_id.as_bytes(),
                surface.as_str().as_bytes(),
                ordinal_text.as_bytes(),
                raw_path_sha256.as_bytes(),
                raw_wire_sha256.as_bytes(),
                parsed.body_sha256.as_bytes(),
                raw_size.as_bytes(),
            ],
        );
        let allow_send_token_sha256 = framed_digest(
            ALLOW_SEND_TOKEN_DOMAIN,
            [
                self.run_binding_sha256.as_bytes(),
                segment_id.as_bytes(),
                intent_id.as_bytes(),
                artifact_binding_sha256.as_bytes(),
            ],
        );
        let receipt = ArtifactReceipt {
            allow_send_token_sha256: &allow_send_token_sha256,
            artifact_binding_sha256: &artifact_binding_sha256,
            authority: false,
            durability_scope: "create_new_file_fsync_then_parent_fsync_before_token",
            enforce: false,
            intent_chain_sha256: &chain,
            intent_id: &intent_id,
            ordinal,
            outbound: false,
            product_http_pre_send_claimed: false,
            promotion: false,
            provider_semantic_sha256: &parsed.provider_semantic_sha256,
            raw_path_sha256: &raw_path_sha256,
            raw_request_body_sha256: &parsed.body_sha256,
            raw_request_size_bytes: raw_request.len(),
            raw_request_wire_sha256: &raw_wire_sha256,
            run_id: &self.run_id,
            sample_token_sha256: &parsed.sample_token_sha256,
            schema: "hepta_shadow_qualification_driver_pre_send_v2",
            schema_version: 2,
            surface,
        };
        write_private_new(&raw_path, raw_request)?;
        write_private_new(&receipt_path, &canonical_json(&receipt)?)?;
        sync_directory(&self.run_root)?;
        self.advance(surface, ordinal, chain)?;
        let token = DurablePreSendToken {
            run_id: self.run_id.clone(),
            surface,
            ordinal,
            token_sha256: allow_send_token_sha256,
        };
        self.tokens.push(token.clone());
        Ok(token)
    }

    fn advance(
        &mut self,
        surface: Surface,
        ordinal: u8,
        chain: String,
    ) -> Result<(), QualificationError> {
        self.stage = match (surface, ordinal) {
            (Surface::AppServer, 1) => Stage::AppServer {
                next_ordinal: 2,
                previous: chain,
            },
            (Surface::AppServer, 2) => Stage::Mcp {
                next_ordinal: 1,
                previous: ZERO_SHA256.to_string(),
            },
            (Surface::Mcp, 1) => Stage::Mcp {
                next_ordinal: 2,
                previous: chain,
            },
            (Surface::Mcp, 2) => Stage::Complete,
            _ => return Err(state("invalid observer transition")),
        };
        Ok(())
    }
}

fn invalid(message: impl Into<String>) -> QualificationError {
    QualificationError::Invalid(message.into())
}

fn state(message: impl Into<String>) -> QualificationError {
    QualificationError::State(message.into())
}
