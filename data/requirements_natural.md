# requirements_natural.csv — column reference

This file contains 20 natural-language diagnostic requirements (NAT-001..NAT-020)
written the way a test engineer would phrase them, paired with machine-scorable
ground-truth labels for evaluating requirement -> test-case generation against
`data/bcm_spec.yaml`.

## Columns

- `id` — `NAT-001` .. `NAT-020`.
- `text` — the natural-language requirement, as an engineer might write it.
  Most avoid hex identifiers and refer to things indirectly (e.g. "the
  unlock step", "the wiper sensitivity calibration"); at most 5 rows
  include a literal hex SID/DID in the text.
- `split` — `dev` (8 rows) or `test` (12 rows), fixed and not to be changed
  after scoring begins.
- `target_services` — semicolon-separated SIDs, uppercase `0xNN`, that a
  complete test for this requirement must exercise. One of:
  `0x10;0x11;0x14;0x19;0x22;0x27;0x2E;0x31;0x3E`.
- `target_dids` — semicolon-separated DID ids, uppercase `0xNNNN`, as
  defined under `dids:` in `bcm_spec.yaml`. Empty if the requirement
  doesn't target a specific DID.
- `target_routines` — semicolon-separated routine ids, uppercase `0xNNNN`,
  as defined under `routines:` in `bcm_spec.yaml`. Empty if none.
- `required_categories` — semicolon-separated subset of exactly:
  `positive;negative;session;security;timing` — the test categories a
  complete test set for this requirement must cover.
- `required_preconditions` — semicolon-separated subset of exactly:
  `default_session; extended_session; programming_session;
  security_level_1; security_level_3; vehicle_stationary; vehicle_moving;
  nvm_fault; dtc_status_set; routine_started; s3_elapsed; lockout_active`,
  or the single token `none`. Security levels match the `level:` values
  under `security_levels:` in the spec (0x01 -> `security_level_1`,
  0x03 -> `security_level_3`).
- `ambiguous` — `true`/`false`. Three rows (NAT-004, NAT-006, NAT-017) are
  deliberately ambiguous.
- `notes` — short explanation; for ambiguous rows, states what is
  ambiguous and which interpretation the other label columns assume. One
  row (NAT-020) describes a capability the spec does not support and has
  empty target columns.
