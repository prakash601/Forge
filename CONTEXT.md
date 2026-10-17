# Forge — Context

Ubiquitous language for the Forge codebase. Terms below are canonical;
use them in issue titles, test names, refactor proposals, and code.
See `docs/design/` for the full contracts.

## Approval

- **Plan approval**: the `plan_approved` event moving a Run from
  `AWAITING_APPROVAL` to `IMPLEMENTING` (see `STATE_MACHINE_v0.1.md` §4).
- **Human approval**: plan approval performed by a person
  (`approved_by: human`).
- **Policy approval**: plan approval performed by the machine under a
  configured policy (`approved_by: policy`). Phase 2 auto-approved every
  plan under `FORGE_AUTO_APPROVE=true`; since v1.0 (#020) plans wait for
  a human unless the global env or the project's `auto_approve_policy`
  flag opts into policy approval. The audit trail records the
  actor so a policy approval is never mistaken for a human one.
- **Approved-by actor**: the `approved_by` value persisted on the
  approval step. Either `human` or `policy`. No approval step is valid
  without it.
