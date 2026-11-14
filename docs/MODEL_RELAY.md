# Model conversation relay

Attack Harness requires the Operator interface version and exact document hash
identified in [the contract lock](../build/contract-lock.json). Both components validate that identity before execution.

Harness sends `engine.model_generate` with `purpose` (`generation` or `compaction`)
and a provider-native `conversation` array. It does not send a model, endpoint,
credential, prompt configuration, provider options, tool declarations or output
limit. Operator constructs those from its frozen host profile. The contract also supports a normally charged, tool-free compaction request;
the adaptive Harness loop uses deterministic local checkpoints instead.

Startup supplies the conversation format (`codec_id`), informational model name,
logical tool availability and context allowances. The response carries a receipt,
opaque provider response JSON and authoritative host usage/budget information.
Harness uses host accounting for compaction and finalization reservations.

The native adapters interpret only completion and tool-call fields they need.
Additional provider metadata does not require a contract change. Native assistant
content, reasoning blocks and signatures are preserved in continuations. Actual
Operator tools still undergo schema, handle, policy and execution-state validation.
Unknown completion states fail explicitly; no automatic replay or argument repair
is performed. Assessment repair and inspected-evidence rules remain in effect.

Controlled tests cover all five provider formats and process transport with a
scripted provider. They do not establish live model reliability.

Context reduction estimates include the frozen prompt and installed tool projection,
even though those bytes are constructed by Operator and absent from relay requests.
Estimates guide reduction only; Operator's validated usage remains authoritative.

Each working conversation is append-only. Evidence inspection and other progress
arrive in new tool results, without refreshing earlier messages. A prefix invariant
checks prior content and frozen policy before submission. Scenario activation,
context reduction, protected finalization and repair use fresh conversations: a
checkpoint contains complete selected requirements and verified campaign state,
without old native assistant/thinking blocks or provider continuation identifiers.
Checkpoints wait until every call in the current response has a result or an
explicit skip. Campaign counters, budgets, handles, repair state and retained
evidence continue unchanged; no target operation is replayed.

A bounded set of recent verified evidence pages may cross a checkpoint as attributed
task data. Other evidence remains available for selective rereading. Finalization
checkpoints include all scenario identities and factual activity, not just the last
active scenario. Neither context renewal nor an execution status establishes an
objective outcome. See [integration behavior](INTEGRATION.md#ordinary-execution)
and the [session specification](../specs/append-only-conversations.md).

For local verification, `make test-pr` checks the conversation and shared validation
suites; `make test-integration` exercises matching Operator/Harness processes with
controlled providers on FIFO and spool. The process checks inspect the effective
provider request after Operator adds its frozen configuration, and verify accepted
finish, exit, cleanup and exported evidence. They do not validate a live provider's
cryptographic signatures or model judgment.

`build/measure_scenario_loading.py` measures the same scenario/restore/repair
sequence against a selected Harness source on `PYTHONPATH`.
`build/measure_context.py --source-root <checkout> --output <file>` also measures
larger observations and any extra rereads. Both report serialized bytes separately
from estimates and leave actual provider usage unset. Checkpoint metadata can
increase the first request while reducing accumulated history later; large omitted
pages may cost an additional read. The checked-in [comparison](../specs/measurements/append-only-conversations.json)
includes those costs and the reproduction inputs.
