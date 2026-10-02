<h1><img src="assets/attack-harness.png" alt="Attack Harness icon" width="48" height="48" align="absmiddle"> Attack Harness</h1>

Attack Harness is the AI-powered testing component of
[Operator Sandbox](https://github.com/intrusiveai/operator_sandbox). It takes a
campaign's objectives and optional scenarios, develops security experiments,
examines the results, and chooses what to try next.

Written in Python, the harness runs inside a network-disabled Docker container
managed by Operator. Operator provides access to model providers and target
applications, enforces campaign limits, and retains evidence. Attack Harness
focuses on planning experiments and adapting them to the feedback it receives.

## How it works

1. **Read the campaign.** The harness receives the objectives, scenarios, target
   capabilities, supporting references, and selected skills from Operator.
2. **Choose an experiment.** It requests model assistance through Operator to
   prepare test inputs and select actions from the available tool catalog.
3. **Run and observe.** It submits the experiment to Operator and reads the
   feedback permitted by the campaign's configuration, including available
   response and artifact content.
4. **Adapt.** It uses those observations to refine inputs, explore another
   scenario, or test a new hypothesis. Where the target supports snapshots, it
   can create, inspect, and restore them while keeping its campaign context.
5. **Conclude.** It records a structured conclusion with evidence references,
   limitations, and untested objectives, then asks Operator to end the campaign.

Campaigns can start from objectives alone or include prepared scenarios.
Custom skills provide additional instructions and reference material; they do
not add executable tools or grant access beyond Operator's configured permissions.
Time, model usage, and operation limits bound the work. Interrupted execution or
an uncertain operation outcome does not trigger automatic replay or resumption.

## Where it fits

| Component | Responsibility |
| --- | --- |
| **Attack Harness** | Plans experiments, creates payloads, interprets feedback, and produces campaign conclusions. |
| **[Operator Sandbox](https://github.com/intrusiveai/operator_sandbox)** | Runs the harness, mediates model and target access, enforces limits, and manages journals, evidence, and reports. |
| **[Interceptor Sandbox](https://github.com/intrusiveai/interceptor_sandbox)** | Supplies a controlled target environment with simulated services, injection controls, snapshots, and recorded observations. |

Operator also supports configured HTTPS targets. The harness sees the operations
available for the selected target and works through Operator's tools. It has no
shell tool, direct network connection, or model-provider credentials.

Harness conclusions are assessments supported by cited observations. Operator
retains those assessments separately from recorded facts so reviewers can see
both the findings and the limits of the evidence.

## Installation and usage

Install and run Attack Harness through **Operator Sandbox**. Start with
[Operator's setup and usage guide](https://github.com/intrusiveai/operator_sandbox#getting-started)
for host installation, model credentials, target configuration, and campaign
commands.

The administrator makes a compatible harness image available in local Docker and
selects it in Operator's `engine.image` configuration. Operator verifies the image's
release compatibility, supplies campaign inputs, and manages container startup
and shutdown. There is no separate user-facing harness CLI to configure or run.

**Development status:** the harness and deterministic integration tests are
implemented. Image approval, complete native runtime qualification, and live
campaign integration remain release prerequisites. Selected host-side provider
probes have passed, but they do not qualify the complete harness/container path.
See [implementation status](IMPLEMENTATION_STATUS.md), the
[acceptance matrix](ACCEPTANCE_MATRIX.md), and
[Operator's live qualification results](https://github.com/intrusiveai/operator_sandbox/blob/main/docs/LIVE_QUALIFICATION_VALIDATION.md).

## Learn more

- [Harness implementation specification](CUSTOM_AI_HARNESS_IMPLEMENTATION_SPEC.md)
- [Container image and artifact layout](GUEST_ARTIFACT_LAYOUT_SPEC.md)
- [Shared Operator–Attack Harness contract](https://github.com/intrusiveai/operator_sandbox/blob/main/schemas/SHARED_CONTRACT.md)
- [Objectives and scenarios format](https://github.com/intrusiveai/operator_sandbox/blob/main/schemas/SCENARIO_BUNDLE_CONTRACT.md)
- [Custom skills](https://github.com/intrusiveai/operator_sandbox/blob/main/docs/SKILLS.md)
- [Host runtime requirements](https://github.com/intrusiveai/operator_sandbox/blob/main/HOST_RUNTIME_PROFILES.md)

## Development

Use Python 3.12 or later and Go 1.26.5. Image builds also need Docker with Buildx.
The shared validation package comes from Operator; use a separate Operator
checkout at the exact `CONTRACT_COMMIT` pinned in this repository's `Makefile`.
Run `make setup` in that checkout to prepare its Python environment and Go dependencies.

By default, the commands below use `../operator_sandbox`. If the pinned checkout
is elsewhere, pass `OPERATOR_ROOT=/absolute/path/to/pinned-operator` to each `make`
command. From this repository:

```sh
make test
make verify-source verify-contracts
```

Build image candidates for either supported container architecture:

```sh
make image PLATFORM=linux/arm64
make image PLATFORM=linux/amd64
```

Build output and candidate evidence are written under the ignored `dist/`
directory. To check the ARM64 candidate with Operator's stopped-image reader,
after the corresponding image build:

```sh
make inspect-stopped-image PLATFORM=linux/arm64
```

This inspects the image without starting the container and checks cleanup. Passing
builds and offline checks do not make an image release-approved. The
[build specification](GUEST_ARTIFACT_LAYOUT_SPEC.md#41-container-build-deliverables)
describes the packaging and qualification requirements.

## License

Attack Harness is licensed under the [GNU AGPL 3.0](LICENSE).
