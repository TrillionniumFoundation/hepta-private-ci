// Copyright 2022 The Matrix.org Foundation C.I.C.
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//     http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.

use base64::Engine as _;
use matrix_sdk_store_encryption::StoreCipher;
use vodozemac::base64_encode;
use zeroize::Zeroize;

use crate::{
    OpenStoreError, Secret,
    error::Result,
    open_diagnostics::{WorkerPhase, capture_open_trace},
};

/// Keep CPU-bound cipher work off the async task that owns database access.
/// Dropping this future cannot stop a started worker; callers retain all writes.
pub(super) async fn run_cipher_work<T, F>(work: F) -> Result<T, OpenStoreError>
where
    T: Send + 'static,
    F: FnOnce() -> Result<T, OpenStoreError> + Send + 'static,
{
    let trace = capture_open_trace();
    if let Some(trace) = &trace {
        trace.worker(WorkerPhase::Submitted);
    }
    tokio::task::spawn_blocking(move || {
        if let Some(trace) = &trace {
            trace.worker(WorkerPhase::Started);
        }
        let result = work();
        if let Some(trace) = &trace {
            trace.worker(WorkerPhase::Returned);
        }
        result
    })
    .await
    .map_err(OpenStoreError::CipherTask)?
}

/// Prepare the original cipher and, when needed, its encrypted database value.
/// Only owned secret material and exported bytes cross the worker boundary.
pub(super) fn prepare_store_cipher(
    secret: Secret,
    encrypted_cipher: Option<Vec<u8>>,
) -> Result<(StoreCipher, Option<Vec<u8>>), OpenStoreError> {
    let mut pending_export = None;
    let cipher = if let Some(encrypted) = encrypted_cipher {
        match &secret {
            Secret::PassPhrase(passphrase) => StoreCipher::import(passphrase, &encrypted)?,
            Secret::Key(key) => StoreCipher::import_with_key(key.as_slice(), &encrypted)?,
            Secret::HighEntropyPassPhrase { key, base64_variant } => {
                // Element X apps used the passphrase-based secret variant even though the
                // underlying secret was a randomly generated key.
                //
                // The `HighEntropyPassPhrase` variant was introduced to migrate these cipher
                // exports from a passphrase-based setup to a key-based setup.
                //
                // We first attempt to decrypt the cipher using the provided high-entropy
                // passphrase as a key. If this results in a KDF mismatch, it indicates that
                // the export was originally encrypted with the high-entropy passphrase being
                // used as a passphrase instead.
                //
                // In that case, we re-encrypt the cipher using the key-based setup. On the next
                // import attempt, `import_with_key()` can then decrypt it successfully.
                match StoreCipher::import_with_key(key.as_slice(), &encrypted) {
                    Ok(cipher) => cipher,
                    Err(matrix_sdk_store_encryption::Error::KdfMismatch) => {
                        // EX generated a byte array for a key but converted it into a string by
                        // base64 encoding it to use it as a passphrase. So let's do that as
                        // well.
                        //
                        // Funnily enough, iOS used padded base64, while Android used unpadded.
                        let mut base64_passphrase = match base64_variant {
                            crate::Base64Variant::Unpadded => base64_encode(key),
                            crate::Base64Variant::Padded => {
                                base64::prelude::BASE64_STANDARD.encode(key)
                            }
                        };

                        let cipher = StoreCipher::import(&base64_passphrase, &encrypted);
                        base64_passphrase.zeroize();

                        let cipher = cipher?;
                        let export = cipher.export_with_key(key.as_slice())?;

                        pending_export = Some(export);

                        cipher
                    }
                    Err(e) => return Err(e.into()),
                }
            }
        }
    } else {
        let cipher = StoreCipher::new()?;

        let export = match &secret {
            Secret::PassPhrase(passphrase) => {
                #[cfg(not(test))]
                {
                    cipher.export(passphrase)
                }
                #[cfg(test)]
                {
                    cipher._insecure_export_fast_for_testing(passphrase)
                }
            }
            Secret::Key(key) => cipher.export_with_key(key.as_slice()),
            Secret::HighEntropyPassPhrase { key, .. } => cipher.export_with_key(key.as_slice()),
        }?;

        pending_export = Some(export);

        cipher
    };

    Ok((cipher, pending_export))
}

#[cfg(test)]
#[path = "store_cipher_tests.rs"]
mod tests;
