# Correcting model tool calls

Use the shared Operator validators and model guidance for the approved contract.
Contract 0.7.1 adds installed-schema constraint references and the
`no-progress-limit` stopping condition. `build/contract-lock.json` pins the exact
version/document hash; implementation source revisions do not determine runtime
compatibility.

Each correctable rejection identifies the model-facing field, failed constraint,
next action, execution effect and safe-resubmission status. Preserve those fields
through wrappers. Schema expectations come from the installed contract; resource
alternatives come from verified campaign state. Never copy unrestricted validator
exceptions or raw rejected payloads into diagnostics. Internal resolution failures
are terminal product errors, not an instruction to supply hidden identities.

The model corrects the identified field, preserves valid request parts, and uses
returned handles exactly. It reads `tool-guide:<name>` when necessary. It must not
repeat an unchanged rejected call or replay completed operations to fix an
assessment. Claims' uncertainty strings reference declared labels; explanatory
prose belongs in the uncertainty's `description`. Full examples and valid enum
values are in `tool-guide:finish`.

Observation reads return separate readable and inspected-citation handles. Follow
`continuation.arguments` to read more; cite only inspected bytes. Reference reads
also provide continuation instructions. Range failures identify applicable bounds.
Compaction retains a bounded recent correction ledger alongside exact handles so
established corrections do not depend on a model-generated summary.

Consecutive turns without recognized progress use `no-progress-limit`, with the
observed count and configured limit. Previous tool rejections remain separately
reported history. An unavailable assessment preserves this reason; exit zero does
not establish a successful campaign when no assessment was committed.

Local verification includes shared malformed/corrected cases, production model
dispatch, no-progress stopping, pagination, and Operator process tests over FIFO
and spool with separate inspection/export. These controlled provider responses do
not establish live-provider reliability. Build and publish matching candidates
through the ordinary release workflow after merge; no special publication path
is required.

Invalid-call exhaustion reports `invalid-call-limit` with reason
`invalid_call_limit`, stage `termination`, the observed count and configured
limit, and `resubmission_safe: false`. Earlier correctable rejections remain
separate diagnostic events; they must not become the stopping cause. The process
regression checks both histories through inspection and exported reports, with no
assessment or target dispatch attributed to rejected calls. This uses the existing
contract identity without changing schemas or raising limits.
