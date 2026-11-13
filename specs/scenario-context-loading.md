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
- Each model request MUST place a compact `active_scenario_activity` record
  beside the complete active scenario in the replaceable user task. It MUST
  derive from retained validated calls and their results, not model summaries or
  target prose. Scenario-origin attempts MUST use their explicit association;
  snapshot creation, restore and injection deletion MUST use the scenario active
  when those actions were submitted. Exploratory attempts MUST NOT acquire a
  scenario association merely because instructions are loaded.
- Activity entries MUST identify the tool, target operation where applicable,
  returned execution status and relevant result/evidence handles. A caller's
  rationale MAY appear as `requested_purpose`, limited to 160 characters and
  explicitly identified as stated intent rather than verified achievement.
  Input payloads and observation bodies MUST NOT be copied into the tracker.
  Associated rejected submissions MUST remain non-executed without invented
  execution handles. Early invalid submissions with no validated association
  MUST remain in ordinary correction history rather than being guessed into a
  scenario. Execution completion MUST NOT mark a scenario requirement satisfied.
- Switching scenarios MUST replace the visible activity record, empty for an
  unvisited scenario. Harness MUST retain earlier records and restore them on
  revisit, including during assessment repair. Duplicate delivery MUST NOT
  create another activity entry or repeat a target operation. Observation
  inspection and content presence MUST refresh from verified state and current
  history, preserving partial-range distinctions. History reduction MUST NOT
  erase activity, snapshot/restore relationships or evidence availability.
  Original request/audit records MUST remain unchanged.
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

Activity regression tests MUST inspect actual controlled provider requests in
all five codecs for an initially empty tracker, a withheld attempt, completion
before evidence inspection, subsequent inspection, switching to an empty
scenario, revisiting prior activity, snapshot/restore, history reduction and a
final assessment that can honestly remain inconclusive. The tracker MUST appear
only in the replaceable task, never as recurring appended history.
