# GPIO Hardware Validation and Documentation Roadmap

## Objective

Finish the GPIO runtime so the same release can be validated predictably in
three environments:

1. Portable simulation on any development machine.
2. Native Raspberry Pi OS on physical hardware.
3. The production container on the same Raspberry Pi hardware.

The final README must be a product-facing guide whose commands have been
verified against those environments. This roadmap covers GPIO only. Camera
endpoints, a simulation-control API, automated GHCR publishing, and backwards
compatibility are outside its scope.

## Current evidence

The native hardware run on a Raspberry Pi 5 established the following baseline:

- Debian Bookworm Python 3.11 can import the OS-owned GPIO packages through the
  project virtual environment.
- A real digital output can be opened, toggled, reset, and closed.
- A real PWM output can be opened, configured, stopped, and closed.
- The initial no-pull input run failed before its first read because GPIO Zero
  requires an explicit `active_state` for a floating input. `HW-01` now
  supplies it and verifies all pull modes in the Bookworm test stage.
- GPIO Zero 2.0.1 cannot open its first-choice `lgpio` controller on the
  validated Raspberry Pi 5 kernel and falls back to
  `gpiozero.pins.rpigpio.RPiGPIOFactory`.
- Native Raspberry Pi OS and the ARM64 container select the same fallback from
  the explicitly installed `python3-rpi-lgpio` package. The four unconnected-pin
  tests pass in the privileged container.
- The current HTTP health check proves that the web process is running; it does
  not prove that the Raspberry Pi provider can initialize or open a GPIO.

These are separate concerns. Input semantics must be corrected in the adapter,
provider selection must be made observable, and host success must not be
treated as container success.

## Design decisions

- Public pin numbers are BCM numbers.
- An input value of `true` means electrical HIGH and `false` means electrical
  LOW. It does not mean GPIO Zero's device-specific "active" state.
- Pull mode controls only the internal resistor. It must not invert the API
  value.
- A no-pull input is valid, but the caller is responsible for an external pull
  or driven signal. An unconnected floating input has no stable expected value.
- `EDGE_HARDWARE_SERVICE_BACKEND` remains the only public backend setting.
  GPIO Zero provider-selection environment variables are not part of the
  service contract.
- The Raspberry Pi runtime initializes one GPIO Zero pin factory and shares it
  across input, digital-output, and PWM devices.
- Provider initialization is performed during application startup in `rpi`
  mode. A process must not report healthy when no physical provider can start.
- No GPIO controller number is hardcoded. Names such as `gpiochip0`,
  `gpiochip4`, and `gpiochip11` are not a stable application contract.
- Hardware tests use explicitly supplied pins and never guess pins that are
  safe to drive.
- Physical tests leave digital outputs LOW and PWM stopped, including on failed
  assertions.
- Production runs one Uvicorn worker because the in-memory pin registry owns
  process-local hardware resources.

## Validation layers

| Layer | Command | Proves | Does not prove |
| --- | --- | --- | --- |
| Portable | `uv run pytest` | Service rules, simulation, schemas, and HTTP behavior | OS packages or physical GPIO |
| Container smoke | `docker run --rm edge-hardware-service:container-smoke-test` | Portable suite works in the image | Device access |
| Pi native | `make pi-hardware-test` | Host OS packages, provider selection, and unconnected GPIO access work | Electrical output levels or container packaging |
| Pi container | `make pi-container-hardware-test` | Image packages and device mapping work on the Pi | Public HTTP workflow |
| Deployed API | `make pi-api-hardware-test` | Real HTTP endpoints, registry, cleanup, and hardware work together | Electrical timing accuracy |

## Native Pi test setup

No external components or wiring are required. Tests use three distinct,
unconnected BCM pins that are not assigned to an active peripheral, overlay, or
another service. Input behavior is checked with the Raspberry Pi's internal
pull-up and pull-down resistors. Output and PWM checks validate provider and
adapter state only; they do not measure voltages, waveforms, electrical timing,
or behavior under load.

## Implementation tickets

### HW-01: Define and correct digital-input semantics

Status: implemented. Portable tests pass and the Bookworm test stage verifies
all three GPIO Zero pull modes without physical hardware. Native pull-up and
pull-down behavior is checked on an unconnected pin in `HW-03`.

**Goal:** Make all supported pull modes construct successfully and return the
electrical pin level promised by the API.

**Work:**

- Document HIGH/LOW semantics in the input protocol, Pydantic schemas, endpoint
  documentation, and backend docstrings.
- Supply the required GPIO Zero `active_state` for a no-pull input.
- Prevent pull-up mode from inverting the public value.
- Keep pull configuration separate from value polarity.
- Add provider-independent contract tests and OS-package adapter tests for
  `none`, `up`, and `down`, including constructor arguments and returned
  polarity.
- Correct the README example only after the behavior is verified.

**Acceptance criteria:**

- `PullMode.NONE`, `PullMode.UP`, and `PullMode.DOWN` all open without GPIO Zero
  configuration errors.
- Electrical HIGH is returned as `true` and LOW as `false` for every pull mode.
- Existing simulation behavior agrees with the physical adapter contract.
- Portable tests cover the provider-independent contract without Raspberry Pi
  imports; the Bookworm test stage covers the GPIO Zero-specific mapping.

### HW-02: Initialize and own the GPIO Zero provider lifecycle

Status: implemented. Portable tests verify simulation import isolation and
service shutdown ordering. The Bookworm container tests verify eager GPIO Zero
initialization, one shared provider across all three device types, provider
logging, startup failure, error translation, and exactly-once cleanup. Physical
host and container provider parity remains part of `HW-04`.

**Goal:** Make Raspberry Pi startup deterministic and expose which provider is
actually in use without adding another public environment flag.

**Work:**

- Initialize GPIO Zero's normal pin-factory selection once when the application
  enters its lifespan in `rpi` mode.
- Share the selected factory with every GPIO Zero device.
- Log the selected factory class and available controller information once at
  startup.
- Fail Raspberry Pi startup clearly when no provider can initialize.
- Close devices before closing the shared provider during shutdown.
- Normalize provider initialization and operation failures into existing
  domain errors so expected hardware failures do not become raw HTTP 500s.
- Add lifecycle tests using injected provider/device doubles.

**Acceptance criteria:**

- Simulation startup still imports no Raspberry Pi modules.
- Raspberry Pi startup either logs one usable provider or fails before the
  health endpoint becomes ready.
- Input, output, and PWM devices use the same provider instance.
- Shutdown releases all devices and then the provider exactly once.
- No pin-factory override environment variable is used or documented.

### HW-03: Replace the native Pi smoke tests with a safe hardware suite

Status: implemented and validated on a Raspberry Pi 5. The suite and SSH
wrapper validate unconnected pin selections, share and report one provider,
verify internal pull-up/pull-down input behavior, exercise output and PWM
lifecycles, and perform ordered safe cleanup.

**Goal:** Validate the real OS libraries, provider, GPIO access, and adapter
logic on a Raspberry Pi without external components or wiring.

**Work:**

- Use one session-scoped physical factory and report the selected GPIO Zero
  provider in pytest output.
- Read an unconnected input with the internal pull-up and pull-down and verify
  the expected levels.
- Retain a digital-output lifecycle test and a PWM configuration/lifecycle test.
- Reset output LOW and PWM to zero in `finally` cleanup before closing devices.
- Detect duplicate, invalid, or missing pin selections before touching hardware.
- Surface busy-line and provider failures with the pin and operation included.
- Update the shell prompt to require confirmation that all selected pins are
  unconnected and safe to drive.

**Acceptance criteria:**

- `make pi-hardware-test` passes without external hardware or `sudo`.
- The suite verifies internal pull-up HIGH and pull-down LOW on an unconnected
  input.
- A failure still leaves the digital output LOW, PWM stopped, and all devices
  closed.
- Missing pins skip or fail before hardware access with an actionable message.
- The command clearly identifies that it runs natively on Raspberry Pi OS.

### HW-04: Establish host and container provider parity

Status: implemented and validated on a Raspberry Pi 5. The ARM64 test target
explicitly installs the primary and fallback GPIO provider packages. Native
Raspberry Pi OS and the container both select
`gpiozero.pins.rpigpio.RPiGPIOFactory`, and all four unconnected-pin tests pass
inside the privileged container.

**Goal:** Ensure the production image contains the OS-level provider that was
proved on the host.

**Work:**

- Record the provider selected by the successful native run and identify its
  owning Debian package.
- Install that package explicitly in the Dockerfile; do not rely on apt
  recommendations or accidental transitive packages.
- Keep Raspberry Pi-native packages outside `pyproject.toml` and `uv.lock`.
- Verify package imports and provider initialization during the appropriate
  ARM64 image stage.
- Add `make pi-container-hardware-test` to transfer and run the test-stage image
  with the same pin inputs and required device access.
- Keep the portable `container-smoke-test` runnable on non-Pi Docker hosts.

**Acceptance criteria:**

- The native and container runs report the intended provider family.
- The container hardware suite passes all real-GPIO tests on the Pi.
- The container does not obtain Raspberry Pi packages from uv or PyPI.
- Simulation mode still starts on a non-Pi machine.
- Required privileges, mounts, and container user identity are explicit in the
  command and documentation.

### HW-05: Add a deployed API hardware smoke test

Status: planned.

**Goal:** Prove the published runtime path, not only the backend class.

**Work:**

- Add `make pi-api-hardware-test` for use after `make deploy`.
- Configure an unconnected input with pull-up and pull-down through HTTP and
  verify both responses.
- Write LOW and HIGH to an unconnected digital output and inspect its status.
- Configure PWM, inspect the typed status and registry, stop PWM, and release
  every opened pin.
- Perform best-effort cleanup when any request or assertion fails.
- Verify that hardware provider errors use the documented `503`
  `hardware_unavailable` schema.
- Distinguish process health from the destructive, opt-in hardware smoke test.

**Acceptance criteria:**

- The test runs against the deployed container over its public API.
- All success payloads validate against the expected response fields.
- Registry state is empty after successful completion and after handled
  failures whenever the API remains reachable.
- No pin is driven until the user confirms the selected output and PWM pins.
- The deployment script cannot claim hardware validation based only on
  `/health`.

### DOC-01: Rewrite README as production documentation

Status: pre-release baseline implemented. The README now provides the product
summary, honest release status, simulation quick start, exact API overview,
runtime configuration, supported image information, architecture, Pi deployment
and validation paths, troubleshooting, validation matrix, development checks,
and the initial release/image-tag policy. GHCR pull commands, CI badges, and
release metadata remain deferred until those artifacts exist.

**Goal:** Give operators, API consumers, and contributors a concise entry point
whose commands match the implemented system.

**Work:**

- Start with the service purpose, supported GPIO capabilities, current scope,
  and simulation-first safety model.
- Add a quick-start path for running simulation locally and opening Swagger.
- Document the single runtime setting in a configuration table.
- Document Raspberry Pi prerequisites, BCM numbering, supported/validated OS
  baseline, unconnected-pin safety, one-worker rule, and container device
  access.
- Separate image use, native development, container deployment, API examples,
  and test commands.
- Add a test matrix explaining what each command proves.
- Add troubleshooting for provider selection, missing `/dev/gpiochip*`, GPIO
  permissions, busy pins, architecture mismatches, and floating inputs.
- Explain pin ownership, release, shutdown, and the process-local registry.
- Link to `docs/architecture.md` for internal design details rather than
  duplicating the architecture roadmap.
- Document GHCR pull commands only when the final repository/image name is
  known; do not publish placeholders as working commands.
- Remove stale claims and confirm every documented command from a clean setup.

**Acceptance criteria:**

- A new user can run simulation and reach Swagger using only the README.
- A Pi operator can identify prerequisites, select safe unconnected pins,
  deploy the image, and run both hardware validations without reading source
  code.
- Destructive or electrically active commands are preceded by clear warnings.
- Host-native testing is never described as container testing.
- All paths, environment variables, target names, endpoint examples, and
  response claims match the repository.
- The README has no unresolved placeholders, roadmap prose, or claims about
  unimplemented camera endpoints.

### QA-01: Perform and record the release validation

Status: planned.

**Goal:** Close the roadmap with evidence from every supported execution layer.

**Work:**

- Run the portable pytest suite.
- Build and run `container-smoke-test` on a normal Docker host.
- Run the native Pi hardware suite with documented unconnected pins.
- Run the container Pi hardware suite with the same pin selections.
- Deploy the runtime image and run the API hardware smoke test.
- Restart the container and confirm that the registry starts empty.
- Review Swagger descriptions and examples against real responses.
- Record the validated Pi model, Raspberry Pi OS release, kernel, architecture,
  Python version, GPIO Zero version, and selected provider in the README.

**Acceptance criteria:**

- All five validation layers pass using the documented commands.
- Output pins are LOW and PWM is stopped after each hardware run.
- Container restart releases resources and clears application state.
- The final README contains the versions actually validated, not assumed
  compatibility claims.
- Any remaining limitation is explicit and has a narrow follow-up ticket.

## Recommended execution order

```text
HW-01 -> HW-02 -> HW-03 -> HW-04 -> HW-05 -> DOC-01 -> QA-01
```

`HW-01` and `HW-02` establish the runtime contract. Hardware tests written
before those contracts are stable would encode the current defects. The README
is intentionally rewritten after the commands and container behavior stop
changing, then `QA-01` verifies the documentation as part of the release.

## Definition of done

- Portable tests pass without Raspberry Pi imports.
- Native and container hardware tests pass with documented unconnected pins.
- The deployed API passes its real-hardware HTTP smoke test.
- Input values have consistent HIGH/LOW meaning in simulation and Raspberry Pi
  modes.
- Raspberry Pi startup selects and reports one usable provider before becoming
  healthy.
- Provider and line failures return stable domain/API errors.
- Every hardware test has deterministic cleanup.
- The production README is accurate, safe, concise, and independently usable.
