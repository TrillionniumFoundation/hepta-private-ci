//! V1's exact route object is unchanged. Explicit V2 requires a complete
//! fixed-input envelope; absent data can never downgrade into the old route.

use super::*;
use crate::authority_host_runtime::PreparedPublicationData;

#[derive(Deserialize)]
#[serde(deny_unknown_fields)]
struct PublicationBootstrapV2 {
    schema: u8,
    route: PublicationBootstrap,
    prepared: PreparedPublicationData,
}

#[derive(Deserialize)]
#[serde(untagged)]
enum VersionedBootstrap {
    Legacy(PublicationBootstrap),
    Durable(PublicationBootstrapV2),
}

#[derive(Serialize)]
struct DurableBootstrapRef<'a> {
    schema: u8,
    route: &'a PublicationBootstrap,
    prepared: &'a PreparedPublicationData,
}

pub(crate) fn encode_original_publication_bootstrap(
    route: &PublicationBootstrap,
    prepared: Option<&PreparedPublicationData>,
) -> io::Result<Vec<u8>> {
    match (PublicationVersion::from_purpose(&route.purpose)?, prepared) {
        (PublicationVersion::LegacyV1, None) => serde_json::to_vec(route),
        (PublicationVersion::DurableV2, Some(prepared)) => {
            serde_json::to_vec(&DurableBootstrapRef {
                schema: 2,
                route,
                prepared,
            })
        }
        _ => {
            return Err(io::Error::other(
                "explicit publication preparation version differs",
            ));
        }
    }
    .map_err(io::Error::other)
}

pub(crate) fn decode_original_publication_bootstrap(
    bytes: &[u8],
) -> io::Result<(PublicationBootstrap, Option<PreparedPublicationData>)> {
    let decoded: VersionedBootstrap = serde_json::from_slice(bytes).map_err(io::Error::other)?;
    match decoded {
        VersionedBootstrap::Legacy(route)
            if PublicationVersion::from_purpose(&route.purpose)?
                == PublicationVersion::LegacyV1 =>
        {
            Ok((route, None))
        }
        VersionedBootstrap::Durable(value)
            if value.schema == 2
                && PublicationVersion::from_purpose(&value.route.purpose)?
                    == PublicationVersion::DurableV2 =>
        {
            Ok((value.route, Some(value.prepared)))
        }
        _ => Err(io::Error::other(
            "original publication preparation is absent or mismatched",
        )),
    }
}
