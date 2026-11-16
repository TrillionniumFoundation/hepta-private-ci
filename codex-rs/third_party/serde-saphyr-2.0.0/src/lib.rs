#![forbid(unsafe_code)]
// The README documents both halves of the default API. Always render it as the
// crate-level documentation, but only extract its doctests when both halves are
// available.
#![cfg_attr(not(doctest), doc = include_str!("../README.md"))]
#![cfg_attr(
    all(doctest, feature = "serialize", feature = "deserialize"),
    doc = include_str!("../README.md")
)]

#[cfg(not(any(feature = "serialize", feature = "deserialize")))]
compile_error!(
    "Invalid feature configuration: enable at least one of \
     \"serialize\" or \"deserialize\"."
);

#[cfg(feature = "deserialize")]
pub use self::de::Budget;
#[cfg(feature = "deserialize")]
pub use self::de::DuplicateKeyPolicy;
#[cfg(feature = "deserialize")]
pub use self::de::Error;
#[cfg(feature = "deserialize")]
pub use self::de::Error as DeserializeError;
#[cfg(feature = "deserialize")]
pub use self::de::MergeKeyPolicy;
#[cfg(feature = "deserialize")]
pub use self::de::NonFiniteFloatPolicy;
#[cfg(feature = "deserialize")]
pub use self::de::Options;
#[cfg(all(feature = "deserialize", feature = "properties"))]
pub use self::de::PropertySyntax;
#[cfg(feature = "deserialize")]
pub use self::de::budget;
#[cfg(feature = "deserialize")]
pub use self::de::localizer;
#[cfg(feature = "deserialize")]
pub use self::de::options;
#[cfg(feature = "deserialize")]
pub use self::de_error::CroppedRegion;
#[cfg(feature = "deserialize")]
pub use self::de_error::MessageFormatter;
#[cfg(feature = "deserialize")]
pub use self::de_error::RenderOptions;
#[cfg(feature = "deserialize")]
pub use self::de_error::SnippetMode;
#[cfg(feature = "deserialize")]
pub use self::de_error::TransformReason;
#[cfg(feature = "deserialize")]
pub use self::de_error::UserMessageFormatter;
#[cfg(all(feature = "deserialize", any(feature = "garde", feature = "validator")))]
pub use self::de_error::ValidationIssue;
#[cfg(all(feature = "deserialize", any(feature = "garde", feature = "validator")))]
pub use self::de_error::ValidationSource;
#[cfg(feature = "deserialize")]
pub use self::indentation::RequireIndent;
#[cfg(feature = "deserialize")]
pub use self::input_source::IncludeRequest;
#[cfg(feature = "deserialize")]
pub use self::input_source::IncludeResolveError;
#[cfg(feature = "deserialize")]
pub use self::input_source::IncludeResolver;
#[cfg(feature = "deserialize")]
pub use self::input_source::InputSource;
#[cfg(feature = "deserialize")]
pub use self::input_source::ResolveProblem;
#[cfg(feature = "deserialize")]
pub use self::input_source::ResolvedInclude;
#[cfg(feature = "deserialize")]
pub use self::localizer::DEFAULT_ENGLISH_LOCALIZER;
#[cfg(feature = "deserialize")]
pub use self::localizer::DefaultEnglishLocalizer;
#[cfg(feature = "deserialize")]
pub use self::localizer::ExternalMessage;
#[cfg(feature = "deserialize")]
pub use self::localizer::ExternalMessageSource;
#[cfg(feature = "deserialize")]
pub use self::localizer::Localizer;
#[cfg(feature = "deserialize")]
pub use self::message_formatters::DefaultMessageFormatter;
#[cfg(feature = "deserialize")]
pub use self::message_formatters::DeveloperMessageFormatter;
#[cfg(feature = "serialize")]
pub use self::ser::Error as SerializeError;
#[cfg(feature = "serialize")]
pub use self::ser::error as ser_error;
#[cfg(all(feature = "serialize", feature = "comments"))]
pub use self::ser::options::CommentPosition;
#[cfg(feature = "serialize")]
pub use self::ser::options::SerializerOptions;
pub use anchors::ArcAnchor;
pub use anchors::ArcRecursion;
pub use anchors::ArcRecursive;
pub use anchors::ArcWeakAnchor;
pub use anchors::RcAnchor;
pub use anchors::RcRecursion;
pub use anchors::RcRecursive;
pub use anchors::RcWeakAnchor;
#[cfg(feature = "figment")]
pub use de::figment;
#[cfg(feature = "figment2")]
pub use de::figment2;
#[cfg(feature = "miette")]
pub use de::miette;
#[cfg(any(feature = "garde", feature = "validator"))]
pub use de::path_map;
#[cfg(feature = "properties")]
pub use de::properties;
#[cfg(feature = "robotics")]
pub use de::robotics;
#[cfg(all(feature = "deserialize", feature = "include_fs"))]
pub use de::safe_resolver::SafeFileReadMode;
#[cfg(all(feature = "deserialize", feature = "include_fs"))]
pub use de::safe_resolver::SafeFileResolver;
#[cfg(all(feature = "deserialize", feature = "include_fs"))]
pub use de::safe_resolver::SymlinkPolicy;
#[cfg(feature = "deserialize")]
pub use granit_parser;
pub use location::Location;
pub use location::Locations;
pub use long_strings::FoldStr;
pub use long_strings::FoldString;
pub use long_strings::LitStr;
pub use long_strings::LitString;
pub use span::Span;
pub use spanned::Spanned;
#[cfg(all(
    feature = "comments",
    any(feature = "serialize", feature = "deserialize")
))]
pub use wrappers::Commented;
#[cfg(any(feature = "serialize", feature = "deserialize"))]
pub use wrappers::DoubleQuoted;
#[cfg(any(feature = "serialize", feature = "deserialize"))]
pub use wrappers::FlowMap;
#[cfg(any(feature = "serialize", feature = "deserialize"))]
pub use wrappers::FlowSeq;
#[cfg(any(feature = "serialize", feature = "deserialize"))]
pub use wrappers::NullableTilde;
#[cfg(any(feature = "serialize", feature = "deserialize"))]
pub use wrappers::SingleQuoted;
#[cfg(any(feature = "serialize", feature = "deserialize"))]
pub use wrappers::SpaceAfter;
#[cfg(any(feature = "serialize", feature = "deserialize"))]
pub use wrappers::Tagged;

#[cfg(feature = "deserialize")]
pub use self::de::api::from_bytes_multiple;
#[cfg(feature = "deserialize")]
pub use self::de::api::from_bytes_multiple_with_options;
#[cfg(feature = "deserialize")]
pub use self::de::api::from_multiple;
#[cfg(feature = "deserialize")]
pub use self::de::api::from_multiple_with_options;
#[cfg(feature = "deserialize")]
pub use self::de::api::from_reader;
#[cfg(feature = "deserialize")]
pub use self::de::api::from_reader_with_options;
#[cfg(feature = "deserialize")]
pub use self::de::api::from_slice;
#[cfg(feature = "deserialize")]
pub use self::de::api::from_slice_multiple;
#[cfg(feature = "deserialize")]
pub use self::de::api::from_slice_multiple_with_options;
#[cfg(feature = "deserialize")]
pub use self::de::api::from_slice_with_options;
#[cfg(feature = "deserialize")]
pub use self::de::api::from_str;
#[cfg(feature = "deserialize")]
pub use self::de::api::from_str_multiple;
#[cfg(feature = "deserialize")]
pub use self::de::api::from_str_multiple_with_options;
#[cfg(feature = "deserialize")]
pub use self::de::api::from_str_with_options;
#[cfg(feature = "deserialize")]
pub use self::de::api::read;
#[cfg(feature = "deserialize")]
pub use self::de::api::read_with_options;
#[cfg(all(feature = "deserialize", feature = "include"))]
pub(crate) use self::de::api::resolver_from_options;
#[cfg(feature = "serialize")]
pub use self::ser::api::to_fmt_writer;
#[cfg(feature = "serialize")]
pub use self::ser::api::to_fmt_writer_with_options;
#[cfg(feature = "serialize")]
pub use self::ser::api::to_io_writer;
#[cfg(feature = "serialize")]
pub use self::ser::api::to_io_writer_with_options;
#[cfg(feature = "serialize")]
pub use self::ser::api::to_string;
#[cfg(feature = "serialize")]
pub use self::ser::api::to_string_multiple;
#[cfg(feature = "serialize")]
pub use self::ser::api::to_string_multiple_with_options;
#[cfg(feature = "serialize")]
pub use self::ser::api::to_string_with_options;

#[cfg(feature = "deserialize")]
mod anchor_store;
mod anchors;
#[cfg(all(
    feature = "serialize",
    feature = "deserialize",
    feature = "include",
    feature = "include_fs"
))]
#[doc(hidden)]
pub mod cli;
#[cfg(feature = "deserialize")]
mod de;
mod location;
mod long_strings;
mod parse_scalars;
#[cfg(feature = "serialize")]
pub mod ser;
mod span;
mod spanned;
#[cfg(any(feature = "serialize", feature = "deserialize"))]
mod tag;
#[cfg(any(feature = "serialize", feature = "deserialize"))]
mod wrappers;

#[cfg(feature = "deserialize")]
pub(crate) use de::buffered_input;
#[cfg(feature = "deserialize")]
pub(crate) use de::error as de_error;
#[cfg(feature = "deserialize")]
pub(crate) use de::include;
#[cfg(all(feature = "deserialize", feature = "include"))]
pub(crate) use de::include_stack;
#[cfg(feature = "deserialize")]
pub(crate) use de::indentation;
#[cfg(feature = "deserialize")]
pub(crate) use de::input_source;
#[cfg(any(feature = "garde", feature = "validator"))]
use de::lib_validate;
#[cfg(feature = "deserialize")]
pub(crate) use de::live_events;
#[cfg(feature = "deserialize")]
pub(crate) use de::message_formatters;
#[cfg(feature = "deserialize")]
pub(crate) use de::properties_redaction;
#[cfg(feature = "deserialize")]
pub(crate) use de::snippet as de_snippet;
#[cfg(feature = "deserialize")]
pub(crate) use de::tags;

#[cfg(feature = "deserialize")]
pub use de::YamlDeserializer as Deserializer;
#[cfg(any(feature = "garde", feature = "validator"))]
pub use lib_validate::*;
#[cfg(feature = "serialize")]
pub use ser::YamlSerializer as Serializer;

#[cfg(feature = "deserialize")]
pub use de::with_deserializer_from_reader;
#[cfg(feature = "deserialize")]
pub use de::with_deserializer_from_reader_with_options;
#[cfg(feature = "deserialize")]
pub use de::with_deserializer_from_slice;
#[cfg(feature = "deserialize")]
pub use de::with_deserializer_from_slice_with_options;
#[cfg(feature = "deserialize")]
pub use de::with_deserializer_from_str;
#[cfg(feature = "deserialize")]
pub use de::with_deserializer_from_str_with_options;

mod macros;
