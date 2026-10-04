"""Bug choices for the simulator tab, grouped by catalog."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from uds_assistant.simulator import (
    DEFAULT_BUG_CATALOG_PATH,
    HELDOUT_BUG_CATALOG_PATH,
    HELDOUT_BUG_IDS,
    HELDOUT_V2_BUG_CATALOG_PATH,
    HELDOUT_V2_BUG_IDS,
    HELDOUT_V3_BUG_CATALOG_PATH,
    HELDOUT_V3_BUG_IDS,
    load_bug_catalog,
)

NO_BUG = "no bug (clean simulator)"


@dataclass(frozen=True)
class BugOption:
    """One selectable bug: id, group and the description shown under the selector."""

    id: str
    group: str
    title: str
    description: str

    @property
    def label(self) -> str:
        return f"[{self.group}] {self.id} ({self.title})"


_GROUPS: tuple[tuple[str, Path, frozenset[str] | None], ...] = (
    ("in-sample", DEFAULT_BUG_CATALOG_PATH, None),
    ("held-out v1", HELDOUT_BUG_CATALOG_PATH, HELDOUT_BUG_IDS),
    ("held-out v2", HELDOUT_V2_BUG_CATALOG_PATH, HELDOUT_V2_BUG_IDS),
    ("held-out v3, fresh", HELDOUT_V3_BUG_CATALOG_PATH, HELDOUT_V3_BUG_IDS),
)


def bug_options() -> list[BugOption]:
    """All bugs, in-sample first; a catalog that cannot be loaded is skipped."""
    out: list[BugOption] = []
    for group, path, ids in _GROUPS:
        try:
            catalog = load_bug_catalog(path)
        except (OSError, ValueError):
            continue
        for b in catalog.bugs:
            if ids is None or b.id in ids:
                out.append(BugOption(b.id, group, b.title, " ".join(b.description.split())))
    return out
