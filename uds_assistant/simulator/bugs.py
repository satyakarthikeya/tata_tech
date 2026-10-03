"""Injectable simulator faults: bug ids and the YAML bug catalog loader.

Each bug id below is implemented by an explicit hook inside the simulator's
service handlers (search for the constant name). The catalog in
``data/bugs/bug_catalog.yaml`` documents every bug for humans and for the
evaluation report; a test checks the catalog and :data:`IMPLEMENTED_BUG_IDS`
stay in sync.

A second, *held-out* set of faults (:data:`HELDOUT_BUG_IDS`, documented in
``data/bugs/heldout_catalog.yaml``) uses the same hook mechanism but is kept
out of :data:`IMPLEMENTED_BUG_IDS`, so anything iterating the original catalog
is unaffected. :data:`ALL_BUG_IDS` is the union accepted by the simulator.
"""

from __future__ import annotations

from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, model_validator

BugCategory = Literal["nrc_order", "session", "security", "timing", "data", "format", "sequence"]
TestCategory = Literal["positive", "negative", "session", "security", "timing"]

_BUGS_DIR = Path(__file__).resolve().parents[2] / "data" / "bugs"
DEFAULT_BUG_CATALOG_PATH = _BUGS_DIR / "bug_catalog.yaml"
HELDOUT_BUG_CATALOG_PATH = _BUGS_DIR / "heldout_catalog.yaml"

# --- bug ids (one constant per hook) ---------------------------------------------------------
NRC_ORDER_DID_BEFORE_SESSION = "nrc_order_did_before_session"
NRC_ORDER_SECURITY_BEFORE_LENGTH = "nrc_order_security_before_length"
GENERAL_REJECT_INSTEAD_OF_0X12 = "general_reject_instead_of_0x12"
SECURITY_NOT_RESET_ON_SESSION_CHANGE = "security_not_reset_on_session_change"
S3_TIMEOUT_NEVER_FIRES = "s3_timeout_never_fires"
S3_TIMEOUT_OFF_BY_ONE = "s3_timeout_off_by_one"
LOCKOUT_AFTER_EXTRA_ATTEMPT = "lockout_after_extra_attempt"
LOCKOUT_DELAY_IGNORED = "lockout_delay_ignored"
LOCKOUT_DELAY_NEVER_EXPIRES = "lockout_delay_never_expires"
ACCEPTS_ANY_KEY = "accepts_any_key"
SEED_NOT_CONSUMED = "seed_not_consumed"
STATIC_SEED = "static_seed"
WRITE_IGNORES_VALUE_RANGE = "write_ignores_value_range"
READONLY_DID_WRITABLE = "readonly_did_writable"
WRITE_LENGTH_OFF_BY_ONE = "write_length_off_by_one"
WRITE_POSITIVE_SID_WRONG = "write_positive_sid_wrong"
SESSION_RESPONSE_MISSING_TIMING = "session_response_missing_timing"
SUPPRESS_BIT_IGNORED = "suppress_bit_ignored"
NEGATIVE_RESPONSE_SUPPRESSED = "negative_response_suppressed"
ROUTINE_STOP_WITHOUT_START = "routine_stop_without_start"
CONDITION_IGNORED = "condition_ignored"
DTC_CLEAR_IGNORES_GROUP = "dtc_clear_ignores_group"
DTC_CLEAR_NOOP = "dtc_clear_noop"
MULTI_DID_READ_FIRST_ONLY = "multi_did_read_first_only"
MISSING_RESPONSE_PENDING = "missing_response_pending"
DTC_READ_IGNORES_MASK = "dtc_read_ignores_mask"

IMPLEMENTED_BUG_IDS: frozenset[str] = frozenset(
    {
        NRC_ORDER_DID_BEFORE_SESSION,
        NRC_ORDER_SECURITY_BEFORE_LENGTH,
        GENERAL_REJECT_INSTEAD_OF_0X12,
        SECURITY_NOT_RESET_ON_SESSION_CHANGE,
        S3_TIMEOUT_NEVER_FIRES,
        S3_TIMEOUT_OFF_BY_ONE,
        LOCKOUT_AFTER_EXTRA_ATTEMPT,
        LOCKOUT_DELAY_IGNORED,
        LOCKOUT_DELAY_NEVER_EXPIRES,
        ACCEPTS_ANY_KEY,
        SEED_NOT_CONSUMED,
        STATIC_SEED,
        WRITE_IGNORES_VALUE_RANGE,
        READONLY_DID_WRITABLE,
        WRITE_LENGTH_OFF_BY_ONE,
        WRITE_POSITIVE_SID_WRONG,
        SESSION_RESPONSE_MISSING_TIMING,
        SUPPRESS_BIT_IGNORED,
        NEGATIVE_RESPONSE_SUPPRESSED,
        ROUTINE_STOP_WITHOUT_START,
        CONDITION_IGNORED,
        DTC_CLEAR_IGNORES_GROUP,
        DTC_CLEAR_NOOP,
        MULTI_DID_READ_FIRST_ONLY,
        MISSING_RESPONSE_PENDING,
        DTC_READ_IGNORES_MASK,
    }
)

# --- held-out bug ids (separate catalog, same hook mechanism) --------------------------------
ROUTINE_STATE_SURVIVES_SESSION_CHANGE = "routine_state_survives_session_change"
FAILED_ATTEMPTS_RESET_BY_SEED_REQUEST = "failed_attempts_reset_by_seed_request"
SEED_RETURNED_WHILE_UNLOCKED = "seed_returned_while_unlocked"
NRC_ORDER_CONDITION_BEFORE_SECURITY = "nrc_order_condition_before_security"
READ_DID_ODD_LENGTH_TRUNCATED = "read_did_odd_length_truncated"
READ_DID_SESSION_RESTRICTION_IGNORED = "read_did_session_restriction_ignored"
UINT16_DID_STORED_BYTE_SWAPPED = "uint16_did_stored_byte_swapped"
S3_NOT_REFRESHED_BY_TESTER_PRESENT = "s3_not_refreshed_by_tester_present"
ECU_RESET_CLEARS_SECURITY_LOCKOUT = "ecu_reset_clears_security_lockout"
S3_TIMEOUT_REVERTS_WRITTEN_DIDS = "s3_timeout_reverts_written_dids"
SESSION_SUPPRESS_BIT_NOT_MASKED = "session_suppress_bit_not_masked"
SUPPRESS_BIT_ECHOED_IN_RESPONSE = "suppress_bit_echoed_in_response"

HELDOUT_BUG_IDS: frozenset[str] = frozenset(
    {
        ROUTINE_STATE_SURVIVES_SESSION_CHANGE,
        FAILED_ATTEMPTS_RESET_BY_SEED_REQUEST,
        SEED_RETURNED_WHILE_UNLOCKED,
        NRC_ORDER_CONDITION_BEFORE_SECURITY,
        READ_DID_ODD_LENGTH_TRUNCATED,
        READ_DID_SESSION_RESTRICTION_IGNORED,
        UINT16_DID_STORED_BYTE_SWAPPED,
        S3_NOT_REFRESHED_BY_TESTER_PRESENT,
        ECU_RESET_CLEARS_SECURITY_LOCKOUT,
        S3_TIMEOUT_REVERTS_WRITTEN_DIDS,
        SESSION_SUPPRESS_BIT_NOT_MASKED,
        SUPPRESS_BIT_ECHOED_IN_RESPONSE,
    }
)

ALL_BUG_IDS: frozenset[str] = IMPLEMENTED_BUG_IDS | HELDOUT_BUG_IDS


class BugDef(BaseModel):
    """One injectable simulator fault."""

    id: str
    title: str
    description: str
    category: BugCategory
    expected_detection: list[TestCategory] = Field(min_length=1)
    heldout: bool = False


class BugCatalog(BaseModel):
    """The full list of injectable faults."""

    bugs: list[BugDef]

    @model_validator(mode="after")
    def _unique_ids(self) -> BugCatalog:
        ids = [b.id for b in self.bugs]
        if len(ids) != len(set(ids)):
            raise ValueError("Duplicate bug ids in catalog.")
        return self

    @property
    def ids(self) -> list[str]:
        """Bug ids in catalog order."""
        return [b.id for b in self.bugs]

    def get(self, bug_id: str) -> BugDef | None:
        """Look up a bug by id."""
        return next((b for b in self.bugs if b.id == bug_id), None)


def load_bug_catalog(path: str | Path = DEFAULT_BUG_CATALOG_PATH) -> BugCatalog:
    """Load and validate the bug catalog YAML."""
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8"))
    return BugCatalog.model_validate(raw)
