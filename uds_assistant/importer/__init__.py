"""Import of existing UDS test cases (YAML) with provenance, oracle validation and review gating.

Format: ``docs/IMPORT_FORMAT.md``. Entry points: :func:`parse_import` (file text -> tests, no
bytes invented) and :func:`import_tests` (validate against the rules engine and record in the
audit trail). Imported tests are never auto-approved.
"""

from __future__ import annotations

from uds_assistant.importer.format import (
    FORMAT_VERSION,
    ImportFormatError,
    ParsedImport,
    ParsedTest,
    parse_import,
)
from uds_assistant.importer.service import (
    IMPORT_LLM_MODE,
    ImportOutcome,
    ImportResult,
    import_tests,
    load_import_result,
)

__all__ = [
    "FORMAT_VERSION",
    "IMPORT_LLM_MODE",
    "ImportFormatError",
    "ImportOutcome",
    "ImportResult",
    "ParsedImport",
    "ParsedTest",
    "import_tests",
    "load_import_result",
    "parse_import",
]
