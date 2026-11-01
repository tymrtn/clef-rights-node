# AI Policy Schema

Clef rights-policy v2 treats AI use as a scoped license, not a binary training flag. The signed policy snapshot and permission receipt preserve the operation, supplied material, model environment, numerical limits, and required controls.

## Operations

- Foundation-model training
- Fine-tuning or model adaptation
- Licensed grounding for generation
- Embedding creation
- Embedding storage and retrieval
- Source separation or stem extraction
- AI remix or music transformation
- Lyric analysis
- Lyric generation or adaptation
- Synthetic voice generation

`ai_training_recursive` remains available only as a labeled compatibility field for v1 policies. New policies use the explicit operations above.

## Supplied material

Each policy separately declares whether the system may receive a full mix, supplied stems, isolated vocals, lyrics, composition/MIDI/score data, or existing reference embeddings. An allowed operation does not override a blocked input asset.

## Model environment

Policies distinguish private single-tenant models, shared commercial models, and public or open-weight models. The recommended organization baseline sends private and shared uses to review and blocks public or open-weight models.

## Limits

Policies can cap source duration, generated-output duration, lyric characters, source retention, and embedding retention. A null limit means the value must be settled in the individual license; it never means unlimited.

## Required controls

The v1 AI policy object declares whether every approved license requires a signed provenance receipt, machine-readable output watermark, attribution, output-similarity review, and source/embedding deletion attestation.

The requester must accept each required control explicitly. Acceptance is recorded in `context.aiUse.acceptedSafeguards`; it is a contractual commitment, not evidence that watermarking, review, attribution, or deletion has already occurred. A missing required acceptance blocks the request.

## Evaluation

An AI request must declare at least one input asset, a model environment, start and end dates, and every required safeguard acceptance. Clef combines the operation state with every input and model-scope state. Any blocked dimension blocks the request; any review dimension prevents automatic approval. A request exceeding a numerical ceiling is blocked.

The resulting evaluation reasons, request scope, policy version, policy hash, and complete policy snapshot are signed into the permission receipt. Composition, master, lyrics, performance, voice, and likeness authority remain separate claims.

## Content restrictions and approval-time checks

Every operation, including AI uses, is subject to `matrix.restrictions`. Requesters declare the complete set of applicable categories in `context.restrictionCategories`, using the published restriction keys; an empty array explicitly declares none applicable. Legacy boolean flags with those keys are accepted, and a true flag remains applicable even alongside an empty list. Political advertising also implies the political category, even if the requester leaves it out or declares it false. Invalid category names and non-boolean flags are rejected.

A declared `denied` category blocks the request; `conditional` requires human review; `allowed` permits evaluation to continue. Omitting the complete declaration when a policy has restrictions produces a pending request and prevents signing until a complete request is submitted. These are requester declarations, not automated analysis of the music or campaign.

Territories use comma-separated two-letter country codes or `worldwide` (legacy whole-world aliases are normalized). Every requested country must fall within the verified claim. A country-specific claim cannot authorize worldwide use; ambiguous territorial descriptions require correction before a grant.

Automatic approvals and human/API decisions use the current policy and current verified authority. A blocked operation, denied content, blocked AI input or model scope, exceeded limit, missing required safeguard, or out-of-territory request prevents signing. PostgreSQL locks the authority and policy rows during the decision transaction. Receipt evaluation reasons describe the policy at issuance; rejected decisions remain available for pending requests whose policy or authority has changed.
