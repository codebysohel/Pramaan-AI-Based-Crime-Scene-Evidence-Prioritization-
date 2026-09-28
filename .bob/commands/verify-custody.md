---
description: Verify the hash-chained chain-of-custody ledger (optionally for one case)
argument-hint: [case_id]
---
Call verify_custody_ledger with case_id $ARGUMENTS (omit if empty). Report whether the chain and the stored result hash are intact; if not, give the first bad sequence number and stop.
