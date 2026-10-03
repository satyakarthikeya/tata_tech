# requirements_natural_v2

A fresh, blind held-out test set of 16 natural-language requirements for the synthetic BCM (data/bcm_spec.yaml). It was written from the spec and the seed requirements only, without seeing any other requirement set. Every row has split = `test2` (no dev part).

Wording is deliberately varied and mostly avoids hex IDs. Two rows are ambiguous (NAT2-014, NAT2-015) and one (NAT2-016) is a requirement the spec does not support, with empty targets.

Columns: id, text, split, target_services (`0xNN`, `;`-separated), target_dids, target_routines (`0xNNNN`), required_categories, required_preconditions, ambiguous (true/false), notes.

- required_categories tokens: positive; negative; session; security; timing
- required_preconditions vocabulary: default_session; extended_session; programming_session; security_level_1; security_level_3; vehicle_stationary; vehicle_moving; nvm_fault; dtc_status_set; routine_started; s3_elapsed; lockout_active; or `none`
- SIDs are limited to 0x10, 0x11, 0x14, 0x19, 0x22, 0x27, 0x2E, 0x31, 0x3E.
