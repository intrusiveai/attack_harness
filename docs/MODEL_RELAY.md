# Model conversation relay

Attack Harness requires Operator interface 0.8.0 with the exact document hash in
`build/contract-lock.json`. Both components validate that identity before execution.

Harness sends `engine.model_generate` with `purpose` (`generation` or `compaction`)
and a provider-native `conversation` array. It does not send a model, endpoint,
credential, prompt configuration, provider options, tool declarations or output
limit. Operator constructs those from its frozen host profile. Compaction makes a
normally charged model call with no available tools.

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
