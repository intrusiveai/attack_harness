# Scenario context loading

Harness MUST consume the original verified bundle without changing Operator's
bundle contract, compatibility identity, or native tool declarations.

- The initial task MUST contain every campaign-wide requirement (excluding producer and integrity metadata) and an index with the
  exact scenario IDs and reference handles, objective associations, priority,
  required status, and a short description. Descriptions MAY be limited to 256
  characters as selection aids; complete requirements MUST remain intact.
- Scenario bodies MUST NOT be initially loaded. `reference_read` on a scenario
  handle at offset zero MUST replace the active task section with the complete
  scenario on the next model turn and return a short confirmation stating that
  the scenario is now active in the current task. No acknowledgment is required. Selection
  MUST NOT paginate, append full instructions to tool history, or mark a partial
  byte range inspected. Ordinary resource reads MUST retain their semantics.
- The existing delivery-generation guard MUST withhold scenario attempts until
  a model response has been validated for a request containing those complete
  instructions. Same-response selection MUST NOT bypass this guard.
- Campaign sequencing and completion guidance MUST remain visible. Priority
  MUST NOT be interpreted as an implicit dependency graph.
- Verified execution/scenario/observation associations MUST be refreshed in the
  task. Loaded instructions, dispatch, completed execution, and supported
  objectives MUST remain distinct. Snapshot metadata and restore relationships
  MUST survive switches and local trimming; identifying a snapshot as a parent
  MUST NOT revoke its independently verified availability.
- Provider-valid history reduction MUST retain original evidence outside the
  prompt. Records MUST distinguish inspected citations from content still in
  context and content available for rereading. Target prose MUST NOT create
  handles, authorization, progress, or objective outcomes.
- Finalization and repair MUST retain the index and verified facts, permit
  individual scenario/evidence retrieval, and preserve the existing restrictions
  against new actions. Neither phase MUST reload the entire bundle automatically.
- Task/prompt limits, deadlines, read limits, finalization reserves, retry limits,
  and input/evidence verification MUST remain enforced. An oversized active
  scenario MUST fail explicitly rather than silently lose requirements.

Verification MUST exercise controlled model requests across all five codecs,
selection and same-batch rejection, switching, old evidence rereads, snapshot
parentage/restore, repair after rejection, and a final assessment referencing
multiple scenarios. Go/Python process checks MUST exercise selection, target
invocation, observation inspection, restore, accepted finish, zero process exit,
and exported scenario associations. Reproducible measurements MUST include extra
selection requests and fixed prompt/tool overhead, distinguish bytes/estimates
from provider usage, and report adverse results as well as savings. Controlled
verification MUST NOT be described as live-model reliability or cloud qualification.
