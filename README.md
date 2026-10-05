# Edge Hardware Service

[![API](https://img.shields.io/badge/API-v1-0A7BBB)](#api-overview)
[![status](https://img.shields.io/badge/status-pre--release-orange)](#project-status)
[![runtime](https://img.shields.io/badge/runtime-Bookworm_ARM64-A22846)](#container-images)
[![Python](https://img.shields.io/badge/Python-3.11-3776AB?logo=python&logoColor=white)](https://www.python.org/)

Containerized HTTP adapter for Raspberry Pi GPIO hardware. Applications use a
small, versioned API instead of depending directly on Raspberry Pi OS hardware
libraries, and the same API runs with an in-memory simulation backend on macOS,
Linux, and CI.

> [!IMPORTANT]
> This project is in pre-release development. GPIO API v1 and the Bookworm
> ARM64 image are functional, but no GHCR image or compatibility guarantee has
> been published yet. Camera libraries are packaged for future work; camera
> endpoints are not currently implemented.

## Quick start

Simulation is the default backend and requires no Raspberry Pi libraries or
hardware.

```shell
uv sync
uv run uvicorn edge_hardware_service.main:app --reload
```

The service is then available at:

- Swagger UI: <http://localhost:8000/docs>
- ReDoc: <http://localhost:8000/redoc>
- OpenAPI JSON: <http://localhost:8000/openapi.json>
- Health check: <http://localhost:8000/api/v1/health>

Try the simulated GPIO API:

```shell
curl --request PUT \
  --header 'Content-Type: application/json' \
  --data '{"value":true}' \
  http://localhost:8000/api/v1/gpio/22/value

curl http://localhost:8000/api/v1/gpio/22
curl http://localhost:8000/api/v1/gpio
```

To use the container locally, build and start the current source tree:

```shell
docker build --platform linux/arm64 --tag edge-hardware-service:dev .
docker run --rm --platform linux/arm64 \
  --publish 8000:8000 \
  edge-hardware-service:dev
```

The production image targets `linux/arm64`. Docker Desktop may use emulation
when the host architecture differs.

## Project status

The current service release is `0.1.0` and the public HTTP contract is API
`v1`. Development currently focuses on GPIO:

- Digital input with no pull, pull-up, or pull-down configuration.
- Digital output reads and writes.
- PWM duty-cycle and frequency control.
- Pin configuration, status, registry inspection, and release.
- Equivalent Raspberry Pi and deterministic simulation backends.

Hardware validation currently covers Raspberry Pi 5 Model B, 64-bit Raspberry
Pi OS Bookworm, and Python 3.11. See the
[hardware validation roadmap](docs/hardware-validation-roadmap.md) for the
exact scope and known limitations.

## Container images

The container is the primary deployment artifact. No public image is available
until the first release; build `edge-hardware-service:dev` locally in the
meantime.

| API | Runtime | Platform | Status | Release image |
| --- | --- | --- | --- | --- |
| v1 | Raspberry Pi OS Bookworm | `linux/arm64` | Pre-release; Pi 5 validated | Planned: `ghcr.io/rasmushaa/edge-hardware-service:<version>-bookworm` |

Raspberry Pi-specific Python packages are installed from the Raspberry Pi OS
apt repository. uv owns only the portable application dependencies. This keeps
GPIO Zero, lgpio, `rpi-lgpio`, libcamera, Picamera2, and the compatible NumPy
build aligned with the operating-system runtime.

The Dockerfile provides three targets:

| Target | Purpose |
| --- | --- |
| `runtime` | Default single-worker production service. |
| `container-smoke-test` | Portable unit and integration tests; safe on macOS/Linux. |
| `rpi-hardware-test` | Opt-in ARM64 GPIO validation on a physical Raspberry Pi. |

Run the portable container test with:

```shell
docker build \
  --target container-smoke-test \
  --tag edge-hardware-service:container-smoke-test \
  .
docker run --rm edge-hardware-service:container-smoke-test
```

## API overview

All public application endpoints use the `/api/v1` prefix. Pin numbers are
Broadcom GPIO numbers (BCM), not physical header positions.

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/api/v1/health` | Check process readiness. |
| `GET` | `/api/v1/gpio` | Inspect the backend and complete open-pin registry. |
| `GET` | `/api/v1/gpio/{pin}` | Inspect one open pin. |
| `PUT` | `/api/v1/gpio/{pin}/configuration` | Configure or reconfigure input, output, or PWM mode. |
| `GET` | `/api/v1/gpio/{pin}/value` | Read a digital input, opening it when needed. |
| `PUT` | `/api/v1/gpio/{pin}/value` | Write a digital output, opening it when needed. |
| `PUT` | `/api/v1/gpio/{pin}/pwm` | Set PWM duty cycle and optional frequency. |
| `DELETE` | `/api/v1/gpio/{pin}` | Close and release a pin. |

Swagger contains the complete request and response schemas, examples for every
supported value, and documented error responses.

Input values are electrical levels: `true` is HIGH and `false` is LOW,
regardless of pull direction. A no-pull input needs an external pull or driven
signal for a stable physical value.

## Runtime configuration

| Environment variable | Values | Default | Meaning |
| --- | --- | --- | --- |
| `EDGE_HARDWARE_SERVICE_BACKEND` | `simulation`, `rpi` | `simulation` | Select the portable in-memory or physical GPIO backend. |

The simulation backend is a supported client-development mode, not a test
mock. It keeps state for the lifetime of the process and exposes the same HTTP
contract without importing Raspberry Pi packages. It does not simulate
electrical circuits or timing.

Raspberry Pi mode initializes one shared GPIO Zero provider during startup.
Startup fails before the health endpoint becomes ready if no provider is
available. The service deliberately uses one Uvicorn worker because GPIO
ownership and the pin registry are process-local.

## Architecture

```text
                         HTTP API v1
                              |
                     FastAPI + Pydantic
                              |
                         GpioService
                  (pin ownership and policy)
                              |
                    GpioDeviceFactory
                         /          \
                        /            \
       GpioZeroDeviceFactory      SimulationDeviceFactory
              Raspberry Pi          macOS / Linux / CI
```

The API layer validates HTTP data, `GpioService` owns pin lifecycle and mode
rules, and interchangeable factories create physical or simulated devices.
Raspberry Pi imports stay entirely outside the simulation startup path. See
[GPIO API architecture](docs/architecture.md) for the detailed boundaries.

## Raspberry Pi deployment

Select the physical backend only on a compatible Raspberry Pi host:

```shell
docker run --rm \
  --name edge-hardware-service \
  --privileged \
  --volume /run/udev:/run/udev:ro \
  --publish 8000:8000 \
  --env EDGE_HARDWARE_SERVICE_BACKEND=rpi \
  edge-hardware-service:dev
```

`--privileged` is the deliberately broad initial configuration because camera
and GPIO discovery can require several device interfaces. Narrow it to the
specific devices and groups validated for the target system before treating
the deployment as hardened.

For the repository's ad hoc SSH workflow:

```shell
make build
make deploy PI_HOST=pi@edgepi.local
```

The deployment transfers the local ARM64 image, replaces the existing
`edge-hardware-service` container, and waits for its health check. It is a
manual development workflow, not a production release mechanism.

## Testing on Raspberry Pi hardware

No external components or wiring are required for the current GPIO validation.
The selected input, digital-output, and PWM pins must be distinct, unconnected,
and unused by another process or peripheral.

Prepare and test the source directly on the Pi:

```shell
make pi-dev-setup
make pi-hardware-test
```

Then validate provider parity and the same GPIO behavior inside the ARM64
container:

```shell
make pi-container-hardware-test
```

Both commands require confirmation before driving pins. The suite verifies
internal pull-up/down input behavior, digital output state, PWM configuration,
provider selection, and safe cleanup; it does not measure physical voltage or
waveform accuracy.

## Development

Python 3.11 and [uv](https://docs.astral.sh/uv/) are required.

```shell
uv sync
uv run pytest
```

Install the repository's fast commit hooks once per clone:

```shell
uv run pre-commit install
```

Run the same checks against the complete repository at any time:

```shell
make lint
make pre-commit
```

Pre-commit checks basic file hygiene, YAML/TOML validity, Python lint rules,
import ordering, and Ruff formatting. Raspberry Pi tests remain opt-in and are
not run by commit hooks.

### Validation matrix

| Command | Environment | What it proves |
| --- | --- | --- |
| `uv run pytest` | macOS/Linux/Pi | Portable service, simulation, and HTTP behavior. |
| `docker run --rm edge-hardware-service:container-smoke-test` | Docker | Portable tests execute in the packaged test image. |
| `make pi-hardware-test` | Raspberry Pi OS | Native OS packages, provider selection, and GPIO access. |
| `make pi-container-hardware-test` | Raspberry Pi + Docker | Native/container provider parity and GPIO access from the ARM64 image. |

### Raspberry Pi troubleshooting

- `Falling back from lgpio` is a warning, not necessarily a failure. Check the
  provider reported after fallback; the validated Pi 5 uses
  `gpiozero.pins.rpigpio.RPiGPIOFactory` from `python3-rpi-lgpio`.
- Missing `/dev/gpiochip*` devices indicate a host or container device-access
  problem, not an API schema problem.
- `GPIO busy` or line-request failures normally mean another process,
  container, overlay, or peripheral owns the selected pin.
- An image architecture other than `arm64` is not the validated Raspberry Pi
  artifact. The provided Make targets check this before transfer.
- A floating input configured with pull `none` has no stable value. Use an
  internal pull or an external circuit when a deterministic physical read is
  required.

## Release and versioning policy

The repository separates three versions:

- API versions are path based, currently `/api/v1`.
- Service releases follow Semantic Versioning and use Git tags such as
  `v1.2.3`.
- Image tags add the Raspberry Pi OS runtime, such as `1.2.3-bookworm`.

During `0.x` development, releases should publish only immutable exact tags
such as `0.1.0-bookworm`. After the first stable release, each Git tag is
expected to publish:

- `MAJOR.MINOR.PATCH-bookworm` — immutable exact release.
- `MAJOR.MINOR-bookworm` — newest compatible patch release.
- `MAJOR-bookworm` — newest compatible release in that service major.

Immutable tags will never be replaced. Consumers should use an exact tag for
reproducible deployments. The floating compatibility tags are for users who
explicitly want updates within a release line. No meaning is assigned to
`latest` until a release workflow documents and enforces one.

Creating Git tags and publishing GHCR images are intentionally outside the
current pre-release workflow.

## Documentation

The repository does not yet include a public license. Add an explicit license
before the first public release so users know how they may use and redistribute
the software.
