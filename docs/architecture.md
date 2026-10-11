# GPIO API architecture and delivery roadmap

## Status

This document defines the proposed target architecture for the GPIO portion of
Edge Hardware Service. It is intentionally small: one HTTP API, one stateful
GPIO service, and interchangeable Raspberry Pi and simulation device factories.

The simulation runtime is a supported product mode. It is not a test mock. Its
purpose is to let other applications integrate with the same HTTP contract on
macOS, Linux, and CI machines without Raspberry Pi libraries or hardware.

This document covers GPIO. The implemented capability-driven camera adapter,
shared MJPEG frame broker, API contract, simulation behavior, and
hardware-validation gates are defined separately in
[`camera-roadmap.md`](camera-roadmap.md).

## Goals

- Keep the implementation easy to read and change.
- Expose one stable GPIO API in Raspberry Pi and simulation modes.
- Keep Raspberry Pi imports completely outside the simulation startup path.
- Make pin ownership, configuration, and current state easy to inspect.
- Produce useful Swagger documentation without requiring readers to inspect the
  source code.
- Give every request and response a named Pydantic schema with realistic
  examples.
- Use Google-style docstrings for backend modules, public classes, and public
  functions.
- Test behavior and contracts rather than maximizing the number of tests.

## Non-goals

- Simulating electrical timing or physical circuits accurately.
- Supporting multiple Uvicorn workers that independently own the same GPIO
  hardware.
- Providing remote multi-host coordination for GPIO ownership.
- Providing simulation-only HTTP endpoints or a separate simulation control
  plane.
- Hiding differences that materially affect client applications. Unsupported
  simulation behavior must be documented explicitly.

## Architectural overview

```text
HTTP client
    |
    v
FastAPI router and Pydantic schemas
    |
    v
GpioService
    |-- owns the active pin registry
    |-- enforces pin-mode rules
    |-- closes and reconfigures devices
    |
    v
GpioDeviceFactory protocol
    |                         |
    v                         v
GpioZeroDeviceFactory   SimulationDeviceFactory
    |                         |
    v                         v
gpiozero devices        Pure-Python simulated devices
```

The service contains GPIO lifecycle policy. Factories only construct the three
device types required by the service:

- Input device
- Digital output device
- PWM output device

This keeps pin-mode and registry logic in one place while preventing gpiozero
from being imported in simulation mode.

## Terminology

Use the following names consistently:

| Term | Meaning |
| --- | --- |
| Raspberry Pi mode | Runtime backed by gpiozero and physical GPIO pins. |
| Simulation mode | Portable, in-memory runtime used to develop API clients. |
| Mock | A test-only replacement controlled by a unit test. |
| Device | One open input, digital-output, or PWM-output pin object. |
| Device factory | Creates devices for one runtime mode. |
| Pin registry | The service-owned collection of currently open pins. |

The runtime configuration values are `simulation` and `rpi`. Do not accept
legacy aliases during this early development phase. Reserve the word `mock` for
test-only replacements.

## Proposed module layout

```text
src/edge_hardware_service/
├── main.py
├── config.py
├── api/
│   ├── dependencies.py
│   ├── errors.py
│   ├── v1.py
│   └── routers/
│       ├── gpio.py
│       └── health.py
├── models/
│   ├── errors.py
│   └── gpio.py
├── services/
│   └── gpio.py
└── hardware/
    └── gpio/
        ├── exceptions.py
        ├── protocols.py
        ├── gpiozero_factory.py
        └── simulation_factory.py
```

### Naming decisions

- `GpioService` is the stateful application service and pin-registry owner.
- `GpioDeviceFactory` is the protocol implemented by both runtime modes.
- `GpioZeroDeviceFactory` creates application adapters around physical gpiozero
  devices.
- `SimulationDeviceFactory` creates pure-Python simulated devices.
- `SimulationInputDevice`, `SimulationDigitalOutputDevice`, and
  `SimulationPwmOutputDevice` describe runtime components. They should not be
  named mocks.
- `GpioServiceDep` is the FastAPI dependency annotation.
- `PinHandle` is an internal service implementation detail and should not be
  returned by the API.

Avoid `RpiGpioBackend` and `GpioDeviceService`. The former mixes runtime and
lifecycle concerns; the latter is less direct than `GpioService`.

## Component responsibilities

### API routers

Routers translate HTTP requests to service calls. They are responsible for:

- Path and request-body validation.
- OpenAPI summaries and Markdown descriptions.
- Selecting named response models.
- Declaring documented error responses.
- Returning HTTP concepts, not hardware device objects.

Routers must not select factories, inspect private service state, or import
gpiozero.

### Pydantic models

Models define the public API contract. They are responsible for:

- Field constraints and descriptions.
- JSON Schema examples displayed in Swagger.
- Request and response serialization.
- Stable public enumeration values.

Models must not own devices or implement GPIO operations.

### `GpioService`

The service is the single owner of the active pin registry. It is responsible
for:

- Lazy pin opening on the first read, digital write, or PWM write.
- Explicit configuration and safe reconfiguration.
- Rejecting operations that conflict with the active pin mode.
- Reading and updating device values.
- Returning public pin-status values derived from internal handles.
- Releasing one pin or all pins.
- Closing every open device during application shutdown.
- Serializing registry mutations so concurrent HTTP requests cannot open the
  same pin twice.

The service receives a `GpioDeviceFactory` in its constructor and contains no
runtime-mode branching.

### Device factories

Both factories implement the same structural protocol:

```python
class GpioDeviceFactory(Protocol):
    def create_input(
        self,
        pin: int,
        pull: PullMode,
    ) -> InputPinDevice: ...

    def create_digital_output(
        self,
        pin: int,
    ) -> DigitalOutputPinDevice: ...

    def create_pwm_output(
        self,
        pin: int,
        frequency_hz: float | None,
    ) -> PwmOutputPinDevice: ...

    def close(self) -> None: ...
```

`GpioZeroDeviceFactory` maps public configuration to gpiozero constructor
arguments, owns one shared GPIO Zero provider, and translates provider failures
into application exceptions.
`SimulationDeviceFactory` stores deterministic, in-memory device state without
adding a second HTTP API.

### Composition root

`main.py` selects the factory once during startup using application settings.
Imports must remain inside the selected branch so simulation mode never imports
the gpiozero implementation.

In Raspberry Pi mode, factory construction initializes GPIO Zero's normal
provider selection before the application begins serving requests. The selected
provider class and visible controller information are logged once. Startup
fails if no provider is usable.

The FastAPI lifespan creates one `GpioService` per process and closes it during
shutdown. The service closes every device before closing the shared provider.
Production must use one Uvicorn worker because the registry and the physical
hardware are process-local resources.

## GPIO behavior

### Pin numbering

All API pin numbers use Broadcom GPIO numbering. Documentation must say `BCM`
where ambiguity is possible. Board-specific validity remains the responsibility
of the selected physical factory until board profiles are deliberately added.

### Lazy configuration

The first operation on an unopened pin assigns its mode:

- Read creates an input device.
- Digital write creates a digital output device.
- PWM write creates a PWM output device.

Later operations in another mode return a mode-conflict response. A client must
explicitly reconfigure or release the pin before changing its purpose.

### Explicit configuration

Explicit configuration safely closes any existing device before opening its
replacement. Configuration applies pull mode for inputs and frequency for PWM
outputs. Parameters that are not implemented must not appear in the public
schema.

### Release and shutdown

Releasing a pin:

1. Calls `close()` on the device.
2. Removes its handle from the service registry after successful cleanup.
3. Makes the pin available for another mode.

Application shutdown attempts to release every registered pin, then closes the
runtime factory exactly once. Cleanup is owned by the FastAPI lifespan, not
`__del__` methods.

### Concurrency

FastAPI synchronous route handlers can run in multiple threads. Registry lookup,
device creation, replacement, and removal must therefore be protected as one
atomic operation. A service-level re-entrant lock is sufficient for this small
application.

## Runtime modes

### Raspberry Pi

- Imports gpiozero only after Raspberry Pi mode is selected.
- Initializes and logs one provider before the application becomes ready.
- Passes that provider explicitly to every input, digital-output, and PWM
  device.
- Uses gpiozero input, digital-output, and PWM-output devices.
- Maps pull and PWM configuration explicitly.
- Converts gpiozero failures into stable service exceptions before they reach
  the router.
- Closes the provider after all device cleanup attempts during shutdown.

### Simulation

- Uses no gpiozero or Raspberry Pi imports.
- Implements the same lazy configuration, mode-conflict, release, and registry
  behavior as Raspberry Pi mode because those rules live in `GpioService`.
- Keeps state in memory for the lifetime of the application process.
- Starts from an empty registry after process restart.
- Exposes exactly the same HTTP endpoints as Raspberry Pi mode.
- Initializes an input as high only when configured with pull-up; pull-down and
  no-pull inputs are initialized as low.
- Retains digital and PWM output values until the device is reconfigured,
  released, or the process stops.
- Rejects reads and writes after a simulated device has been closed.

The GPIO router is identical in both modes. Simulation behavior that cannot be
controlled through the standard API remains an explicit simulator limitation
rather than creating a second control surface.

The simulator does not model external electrical signals, timing, connected
circuits, hardware failures, or state persistence. It deliberately provides no
simulation-only method or endpoint for changing input state.

## Proposed HTTP API

The canonical API prefix should be `/api/v1`. The existing `/app/v1` prefix can
be changed before the API is published.

### Standard GPIO API

| Method | Path | Success response | Purpose |
| --- | --- | --- | --- |
| `GET` | `/api/v1/gpio` | `PinRegistryResponse` | Inspect all currently open GPIO resources and their configuration. |
| `GET` | `/api/v1/gpio/{pin}` | `PinStatus` | Inspect one open GPIO resource. |
| `PUT` | `/api/v1/gpio/{pin}/configuration` | `PinStatus` | Explicitly configure or reconfigure a GPIO resource. |
| `GET` | `/api/v1/gpio/{pin}/value` | `DigitalReadResponse` | Read an input, lazily opening it if needed. |
| `PUT` | `/api/v1/gpio/{pin}/value` | `DigitalOutputStatus` | Write a digital output, lazily opening it if needed. |
| `PUT` | `/api/v1/gpio/{pin}/pwm` | `PwmOutputStatus` | Set PWM duty cycle and optional frequency. |
| `DELETE` | `/api/v1/gpio/{pin}` | `PinReleaseResponse` | Release one GPIO resource and report whether it was open. |

Use `200` responses rather than `204` where a documented response schema is
valuable. The returned state makes client development and debugging easier.

## Public schemas

Every request body and success response has a named Pydantic model. Reuse a
shared `ErrorResponse` for documented errors.

### Request models

- `PinConfigurationRequest`
  - `mode`
  - `pull` for input mode
  - `frequency_hz` for PWM mode
- `DigitalWriteRequest`
  - `value`
- `PwmWriteRequest`
  - `duty_cycle`
  - optional `frequency_hz`

### Response models

- `DigitalReadResponse`
- `InputPinStatus`
- `DigitalOutputStatus`
- `PwmOutputStatus`
- `PinStatus`, a discriminated union using `mode`
- `PinRegistryResponse`
- `PinReleaseResponse`
- `ErrorResponse`

The status union prevents ambiguous combinations of nullable fields. For
example, a PWM status always contains a duty cycle, while an input status always
contains a boolean value and pull configuration.

`PinRegistryResponse` should include:

- Active runtime mode.
- Number of open pins.
- List of typed pin statuses ordered by pin number.

Each model must define realistic Swagger examples with
`ConfigDict(json_schema_extra={"examples": [...]})`. Fields need concise
descriptions and useful constraints, such as duty cycle between `0.0` and `1.0`.

## Endpoint documentation standard

Each operation declares:

- A concise `summary`.
- A stable `operation_id` suitable for generated clients.
- A multiline Markdown `description`.
- A named success `response_model`.
- Documented error models and status codes.

Descriptions should explain behavior a caller cannot infer from the path. Use
short bullet points. For example:

```python
@router.get(
    "/{pin}/value",
    summary="Read a digital input",
    operation_id="read_gpio_input",
    description="""
Read the current electrical level of a BCM GPIO pin.

- An unopened pin is automatically configured as an input.
- The default pull mode is `none` unless configured explicitly.
- An unconnected input with pull mode `none` may return an unstable value.
- Reading a pin already opened as an output returns `409 Conflict`.
- The returned value is `true` for electrical HIGH and `false` for LOW,
  regardless of pull direction.
""",
    response_model=DigitalReadResponse,
)
```

Do not fill descriptions with generic text such as "Reads a pin." Every bullet
must help an API consumer make a correct call or understand a state transition.

## Error contract

Expected service failures derive from one `AppError` base and are rendered by
one API exception handler. FastAPI request validation is adapted to the same
response contract. Unexpected programming failures remain opaque `500`
responses.

Recommended mappings:

| Status | Error code | Meaning |
| --- | --- | --- |
| `404` | `not_found` | A required application resource does not exist. |
| `409` | `conflict` | The request conflicts with the current resource state. |
| `422` | `invalid_request` | Input is invalid or a requested capability is unsupported. |
| `503` | `hardware_unavailable` | The physical provider cannot access the hardware. |
| `504` | `operation_timeout` | A hardware operation exceeded its deadline. |

An error response contains a stable machine-readable code, a human-readable
message, and optional structured details such as pin and active mode.

## Documentation and code-quality conventions

Backend modules begin with a module docstring explaining their responsibility
and runtime dependencies. Public backend classes and functions use Google-style
docstrings with the applicable sections:

- `Args`
- `Returns`
- `Raises`
- `Attributes`

Protocol methods document behavioral contracts rather than repeating type
annotations. Comments explain reasons and invariants, not line-by-line mechanics.

Names should use `simulation` for runtime behavior and reserve `mock` for test
objects. Keep imports ordered as standard library, third party, then local.

## Runtime dependency ownership

uv and `pyproject.toml` own only the portable Python application dependencies,
including FastAPI, Uvicorn, Pydantic, and the simulation runtime. They must not
declare gpiozero, lgpio, or other Raspberry Pi-specific packages.

The Debian Bookworm container owns Raspberry Pi dependencies. It installs them
with `apt`, and its virtual environment is configured to see the corresponding
OS-level Python package directory. These packages are therefore available only
inside the intended container environment and are not represented in the uv
lockfile.

The runtime setting is `EDGE_HARDWARE_SERVICE_BACKEND`, with `simulation` as
the safe default and `rpi` enabling physical GPIO. The setting is supplied when
the container starts; it is not a build argument and does not require separate
images for simulation and Raspberry Pi modes.

This boundary makes lazy importing mandatory:

- Simulation mode must start without importing the Raspberry Pi factory module.
- Raspberry Pi mode imports its factory only after configuration selects it.
- Selecting Raspberry Pi mode outside the prepared container must fail with a
  clear configuration/startup message identifying the unavailable OS package.

Development dependencies such as pytest and the HTTP test client belong in a uv
development dependency group.

## Test strategy

Tests should protect behavior that is important to API consumers or hardware
ownership. Coverage is a diagnostic, not the goal.

### Service unit tests

Use small controlled device/factory fakes to verify:

- First read opens an input with the correct pull mode.
- First digital write opens an output and stores the value.
- First PWM write opens a PWM device and applies duty cycle and frequency.
- A conflicting operation raises `ConflictError` without replacing the
  existing device.
- Reconfiguration closes the old device exactly once and replaces it.
- Release closes and removes a pin.
- Shutdown closes every open device even when one close fails.
- Concurrent attempts cannot create two devices for one pin.
- Registry output is complete, typed, and consistently ordered.

### Simulation unit tests

Verify the runtime simulator independently:

- All three simulated device types implement their protocols.
- Closed devices reject further access.
- One pin cannot be reserved twice while open.
- A closed pin can be reopened in another mode.
- Input values follow the simulator's documented deterministic defaults.
- Service shutdown closes devices and clears active state.

### API tests

Use FastAPI `TestClient` with simulation settings to verify complete user-visible
flows:

- Health and startup in simulation mode without importing the Raspberry Pi
  factory.
- Digital read, digital write, PWM, configuration, status, registry, and release.
- Mode conflicts and validation failures return documented error schemas.
- Every operation has a summary, Markdown description, operation ID, response
  model, and expected examples in the generated OpenAPI document.

Prefer scenario tests that cover a meaningful state transition over one test per
line or trivial Pydantic behavior.

### Bookworm container and Raspberry Pi validation

Default development and CI runs must not require Raspberry Pi packages or
hardware. A prepared Raspberry Pi OS Bookworm host is the authoritative
environment for OS-library, provider, and GPIO device-access compatibility; the
production container must later prove parity on the same Pi.

Keep the native functional suite short, explicit, and repeatable:

- Validate three distinct operator-selected BCM pins before opening hardware.
- Verify an unconnected input using the Pi's internal pull-up and pull-down.
- Toggle and reset a known safe digital output.
- Apply two PWM duty cycles and stop PWM.
- Reset outputs before closing devices, then close the shared provider.

No external components or wiring are required; all selected pins must remain
unconnected. The suite validates library and application behavior, not physical
output voltages, PWM waveforms, or electrical timing. It is opt-in and is not
part of the normal uv-managed test run.
The production container should also be exercised frequently in simulation
mode to validate startup, Swagger, and ordinary client workflows without
touching hardware. Container access to physical GPIO is validated separately
using the same unconnected pin selections.

The GPIO container validation uses a dedicated ARM64 test target derived from
the same OS-package layer as the runtime image. It reports apt-owned GPIO
packages, compares the host and container provider class, then runs the native
suite as root with `--privileged` and a read-only `/run/udev` mount. This
matches the current production container and permits native GPIO notification
pipes under the root-owned working directory. The broad device access is an
explicit initial compatibility configuration; it is not a claim that every
privileged device is required by GPIO.

## Delivery roadmap

Each item is intended to become a small implementation ticket with explicit
acceptance criteria.

### 1. Normalize GPIO naming and module boundaries

Status: implemented.

- Apply the proposed names and module layout.
- Move device protocols and GPIO exceptions under `hardware/gpio`.
- Keep the existing HTTP behavior working during the move.
- Remove unused or misleading classes and imports.

### 2. Complete the shared `GpioService`

Status: implemented.

- Inject `GpioDeviceFactory`.
- Correct lazy opening, explicit configuration, reconfiguration, and cleanup.
- Add thread-safe registry ownership.
- Add typed status and registry queries.
- Remove destructor-based cleanup.

### 3. Complete the simulation runtime

Status: implemented.

- Implement all three simulated device types.
- Enforce open and closed lifecycle behavior.
- Ensure the simulation path imports no Raspberry Pi implementation.
- Document deterministic input behavior and other simulator limitations.

### 4. Complete the gpiozero factory

Status: implemented in code. Input semantics were corrected in `HW-01`, and
provider lifecycle ownership was completed in `HW-02`. Native digital-output
and PWM validation pass; native internal-pull input and container hardware
validation remain open in
[`hardware-validation-roadmap.md`](hardware-validation-roadmap.md).

- Construct all three gpiozero device types.
- Apply pull configuration and PWM frequency.
- Normalize provider failures into service exceptions.
- Initialize, report, share, and close one GPIO Zero provider per application
  lifespan.
- Keep gpiozero imports isolated to this module.
- Validate imports and device creation inside the Bookworm container with
  OS-installed packages.

### 5. Define the public Pydantic contract

Status: implemented.

- Add all named request, response, status, registry, and error models.
- Add field descriptions, constraints, and realistic examples.
- Use a discriminated union for pin status.
- Remove public fields that have no implemented behavior.

### 6. Finish the standard GPIO endpoints

Status: implemented.

- Implement configuration, read, digital write, PWM, status, registry, release,
  and error responses.
- Use the `/api/v1` prefix.
- Use `/api/v1/gpio` as the collection path without an additional `/pins`
  segment.
- Return typed responses for every success path.
- Add useful Markdown descriptions to every operation.

### 7. Add focused automated tests

Status: implemented. Raspberry Pi hardware tests remain opt-in, require three
unconnected pins, and validate all selected BCM pins before hardware access.

- Add pytest through uv.
- Implement the service, simulation, and API scenarios listed above.
- Make `uv run pytest` the documented default test command.
- Confirm the default suite neither imports nor requires Raspberry Pi packages.

### 8. Finish runtime and contributor documentation

Status: expanded into the focused hardware-validation and documentation
roadmap in [`hardware-validation-roadmap.md`](hardware-validation-roadmap.md).

- Document simulation and Raspberry Pi startup commands.
- Document the single-worker requirement and BCM numbering.
- Document simulation limitations.
- Document the Bookworm container's apt-installed Python dependencies and
  external OS-package path wiring into the virtual environment.
- Add container health-check guidance, a manual test workflow, and Raspberry Pi
  device requirements.

## Definition of done for GPIO API work

- The application starts in simulation mode on a non-Raspberry Pi machine
  without importing Raspberry Pi modules.
- The same standard endpoints and schemas work in both runtime modes.
- Swagger provides actionable Markdown descriptions and realistic examples.
- All normal and error responses use documented Pydantic schemas.
- Registry inspection shows every active pin and its effective configuration.
- Shutdown deterministically closes all devices.
- `uv run pytest` passes the focused service, simulation, and API suite.
- Public backend code has accurate Google-style module, class, and function
  docstrings.
- The Raspberry Pi runtime is configured for one process and has an explicit
  Bookworm-container hardware smoke-test procedure.
