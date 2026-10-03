# requirements_natural_v3

Fresh blind test set of 16 natural-language requirements for the synthetic BCM UDS spec (data/bcm_spec.yaml). Written without seeing any other requirement set; all rows have split `test3` (no dev part).

Columns: id,text,split,target_services,target_dids,target_routines,required_categories,required_preconditions,ambiguous,notes

- target_services: semicolon-separated SIDs, 0xNN uppercase.
- target_dids / target_routines: semicolon-separated 0xNNNN ids from the spec (empty if none).
- required_categories: subset of positive;negative;session;security;timing.
- required_preconditions: subset of default_session; extended_session; programming_session; security_level_1; security_level_3; vehicle_stationary; vehicle_moving; nvm_fault; dtc_status_set; routine_started; s3_elapsed; lockout_active, or `none`.
- ambiguous: true/false (2 rows, reasons in notes). NAT3-016 is deliberately unsupported by the spec (empty targets).
- Most rows avoid hex IDs; at most 4 contain one.
