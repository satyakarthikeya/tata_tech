"""Independent simulated ECU (never imports :mod:`uds_assistant.rules`).

Public API:

- :class:`SimulatedEcu` — stateful ECU, ``handle(request, now_ms) -> list[bytes]``.
- :func:`load_bug_catalog` / :data:`IMPLEMENTED_BUG_IDS` — injectable faults;
  :data:`HELDOUT_BUG_IDS` / :data:`HELDOUT_BUG_CATALOG_PATH` — the held-out set.
- :class:`InProcessTransport`, :class:`EcuCanServer`, :class:`IsoTpClientTransport`
  — ways to talk to the ECU.
"""

from __future__ import annotations

from uds_assistant.simulator.bugs import (
    ALL_BUG_IDS,
    DEFAULT_BUG_CATALOG_PATH,
    HELDOUT_BUG_CATALOG_PATH,
    HELDOUT_BUG_IDS,
    HELDOUT_V2_BUG_CATALOG_PATH,
    HELDOUT_V2_BUG_IDS,
    IMPLEMENTED_BUG_IDS,
    BugCatalog,
    BugDef,
    load_bug_catalog,
)
from uds_assistant.simulator.ecu import SimulatedEcu
from uds_assistant.simulator.transport import (
    EcuCanServer,
    InProcessTransport,
    IsoTpClientTransport,
)

__all__ = [
    "ALL_BUG_IDS",
    "DEFAULT_BUG_CATALOG_PATH",
    "HELDOUT_BUG_CATALOG_PATH",
    "HELDOUT_BUG_IDS",
    "HELDOUT_V2_BUG_CATALOG_PATH",
    "HELDOUT_V2_BUG_IDS",
    "IMPLEMENTED_BUG_IDS",
    "BugCatalog",
    "BugDef",
    "EcuCanServer",
    "InProcessTransport",
    "IsoTpClientTransport",
    "SimulatedEcu",
    "load_bug_catalog",
]
