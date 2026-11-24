"""String contracts owned by the application boundary.

Namespaces contain plain Final strings only; they own no configuration defaults.
"""
from typing import Final


class TextFileEncoding:
    """Text encodings shared by geospatial input and report I/O."""

    UTF8: Final[str] = 'utf-8'  # Common text/report encoding; writes do not add a BOM.
    UTF8_BOM: Final[str] = 'utf-8-sig'  # Configuration reception accepts an optional UTF-8 BOM.


class ProgressEventFields:
    """CLI progress event metadata, distinct from object quality records."""

    PHASE: Final[str] = 'phase'  # Wire key for progress event phase.
    EXCLUDED_COUNT: Final[str] = 'excluded'  # Excluded-object count in a progress event, not an object status value.
    OBJECT_COUNT: Final[str] = 'objects'  # Object count in a progress event, not a collection of quality records.


class ApplicationIdentity:
    """Application name emitted in generated model metadata."""

    NAME: Final[str] = '3DLodExt'  # Application name used in generated metadata.


class OutputDirectoryMessages:
    """Shared output-preservation guard wording; exception type stays at caller."""

    OUTPUT_EXISTS: Final[str] = 'Output directory already exists'  # Shared new-output guard; caller preserves exception type.


class CommandLineArguments:
    """Shared CLI spellings and help for the application and audit tools."""

    OUTPUT_OPTION: Final[str] = '--output'  # Shared local CLI output option spelling.
    DATA_OPTION: Final[str] = '--data'  # Shared audit CLI fixture option spelling.
    RELATIVE_Z_OPTION: Final[str] = '--experimental-relative-z'  # Explicit audit-only local-Z opt-in option.
    NEW_RUN_HELP: Final[str] = 'New run directory'  # Shared CLI hint; existing directories are rejected.
    FIXTURE_HELP: Final[str] = 'Local fixture directory'  # Shared local audit fixture argument hint.
    CONFIG_POSITIONAL: Final[str] = 'config'  # Positional configuration-file argument; not effective run settings.
    SUBCOMMAND_DESTINATION: Final[str] = 'command'  # Parsed command attribute; not a report field.
