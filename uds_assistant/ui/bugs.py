"""Bug choices for the simulator: the in-sample catalog plus the blind v3 set."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from uds_assistant.simulator import (
    DEFAULT_BUG_CATALOG_PATH,
    HELDOUT_V3_BUG_CATALOG_PATH,
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


_GROUPS: tuple[tuple[str, Path], ...] = (
    ("in-sample", DEFAULT_BUG_CATALOG_PATH),
    ("blind v3", HELDOUT_V3_BUG_CATALOG_PATH),
)


def bug_options() -> list[BugOption]:
    """All bugs, in-sample first; a catalog that cannot be loaded is skipped."""
    out: list[BugOption] = []
    for group, path in _GROUPS:
        try:
            catalog = load_bug_catalog(path)
        except (OSError, ValueError):
            continue
        for b in catalog.bugs:
            out.append(BugOption(b.id, group, b.title, " ".join(b.description.split())))
    return out
