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
5. **Conclude.** It submits one assessment with evidence references, limitations,
   and untested objectives. Operator retains it, closes execution, and performs
   cleanup; the Harness exits after acceptance.

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
[Operator's setup and usage guide](https://github.com/intrusiveai/operator_sandbox/blob/d9255aeba9618bd53f4c3344e6f1c4284e99a353/README.md#getting-started)
for host installation, model credentials, target configuration, and campaign
commands.

The administrator makes a compatible harness image available in local Docker and
selects it in Operator's `engine.image` configuration. Operator verifies the image's
embedded image compatibility, supplies campaign inputs, and manages container startup
and shutdown. There is no separate user-facing harness CLI to configure or run.

Release **v0.1.0** requires Operator version **0.1.0 or later** with the exact
shared contract **0.2.1** package digest pinned by this release. The
[integration guide](docs/INTEGRATION.md) provides the immutable contract identity,
image selection steps, tool examples, and compatibility checks.

## Learn more

- [Runtime behavior and architecture](CUSTOM_AI_HARNESS_IMPLEMENTATION_SPEC.md)
- [Container image and artifact layout](GUEST_ARTIFACT_LAYOUT_SPEC.md)
- [Shared Operator–Attack Harness contract](https://github.com/intrusiveai/operator_sandbox/blob/754b7119f49850727c6df506f050eae11d7af915/schemas/SHARED_CONTRACT.md)
- [Objectives and scenarios format](https://github.com/intrusiveai/operator_sandbox/blob/754b7119f49850727c6df506f050eae11d7af915/schemas/SCENARIO_BUNDLE_CONTRACT.md)
- [Custom skills](https://github.com/intrusiveai/operator_sandbox/blob/d9255aeba9618bd53f4c3344e6f1c4284e99a353/docs/SKILLS.md)
- [Host runtime requirements](https://github.com/intrusiveai/operator_sandbox/blob/d9255aeba9618bd53f4c3344e6f1c4284e99a353/HOST_RUNTIME_PROFILES.md)

## Development

Use Python 3.12 or later and Go 1.26.5; CI uses Python 3.13.15. Image builds need
Docker and Buildx with the versions pinned in `.github/workflows/verify.yml`.
The shared Python package is supplied by Operator's locked source, not a public
package-index installation.

Prepare two Operator checkouts using the exact
[contract source and runtime pins](docs/INTEGRATION.md#locked-contract-and-runtime).
The contract checkout produces the package; the runtime checkout supplies the
host used for process integration and image inspection. From this repository:

```sh
python3 -m venv .ci-venv
.ci-venv/bin/python -m pip install --require-hashes --only-binary=:all: --no-deps -r requirements-runtime.lock
make contract-package OPERATOR_ROOT=/absolute/path/to/contract-source
make verify-source verify-contracts OPERATOR_ROOT=/absolute/path/to/contract-source PYTHON=.ci-venv/bin/python
make test OPERATOR_ROOT=/absolute/path/to/contract-source PYTHON=.ci-venv/bin/python
make test-integration OPERATOR_ROOT=/absolute/path/to/matching-operator PYTHON=.ci-venv/bin/python
```

The generated package is stored in ignored `build/context/contracts`. Build and
inspect either platform, substituting `linux/amd64` for AMD64:

```sh
make image PLATFORM=linux/arm64 OPERATOR_ROOT=/absolute/path/to/contract-source PYTHON=.ci-venv/bin/python
make inspect-stopped-image PLATFORM=linux/arm64 OPERATOR_ROOT=/absolute/path/to/matching-operator PYTHON=.ci-venv/bin/python
```

Build output is written under ignored `dist/`. Stopped-image inspection checks
release files and inspection-container removal without running a campaign. See
[the image build and inspection guide](GUEST_ARTIFACT_LAYOUT_SPEC.md#build-and-inspection-commands)
for artifact identities and runtime boundaries.

## License

Attack Harness is licensed under the [GNU AGPL 3.0](LICENSE).
