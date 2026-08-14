# Adapter Contract

Every external adapter declares capabilities independently:

- `catalog_lookup`
- `ownership_evidence_read`
- `work_registration_write`
- `claim_submission_write`
- `permission_request_exchange`
- `usage_reporting_write`
- `royalty_statement_read`

An adapter must report whether each capability is configured, reachable, authorized, and last verified. Credentials alone never mark a capability authorized. Production calls fail closed when the requested capability is unavailable.

MLC adapters are treated as musical-work data and authorized member-workflow adapters. They are not derivative, master, sync, lyrics, voice, or likeness permission authorities.

The node operator holds the upstream MLC credential. Organization systems use organization-bound Clef credentials with registry-read scope. Successful lookups are recorded as observed, permission-unknown reads with query digests; raw criteria and upstream credentials do not enter the organization audit record.

The DDEX MWL adapter exports only US musical-work licensing messages. It does not convert a Clef derivative-work, master, voice, likeness, or lyrics permission into a DDEX grant. MWL rights and usage mappings must be declared explicitly for every export.

Generated exchanges and observed partner acknowledgements are append-only evidence. Acknowledgement status is never applied to a Clef permission automatically; legal or operational effects require an explicit, separately authorized workflow.
