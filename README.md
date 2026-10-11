# Edge Hardware Service

[![API](https://img.shields.io/badge/API-v1-0A7BBB)](#api-overview)
[![status](https://img.shields.io/badge/status-pre--release-orange)](#project-status)
[![runtime](https://img.shields.io/badge/runtime-Bookworm_ARM64-A22846)](#container-images)
[![Python](https://img.shields.io/badge/Python-3.11-3776AB?logo=python&logoColor=white)](https://www.python.org/)
[![license](https://img.shields.io/badge/license-MIT-green)](LICENSE)

Containerized HTTP adapter for Raspberry Pi GPIO and Picamera2-compatible
cameras. Applications use a small, versioned API instead of depending directly
on Raspberry Pi OS hardware libraries, and the same API runs with deterministic
simulation backends on macOS, Linux, and CI.

> [!IMPORTANT]
> This project is in pre-release development. GPIO API v1 and the Bookworm
> ARM64 image are functional, but no GHCR image or compatibility guarantee has
> been published yet. Camera support discovers Picamera2 sensor modes and
> controls at runtime; only hardware explicitly named in the validation notes
> should be treated as physically validated.

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
`v1`. The service currently provides:

- Digital input with no pull, pull-up, or pull-down configuration.
- Digital output reads and writes.
- PWM duty-cycle and frequency control.
- Pin configuration, status, registry inspection, and release.
- Equivalent Raspberry Pi and deterministic simulation backends.
- One shared MJPEG camera stream, latest-image access, runtime capability
  discovery, optional focus controls, and nullable telemetry.

Hardware validation currently covers Raspberry Pi 5 Model B, 64-bit Raspberry
Pi OS Bookworm, and Python 3.11. See the
[hardware validation roadmap](docs/hardware-validation-roadmap.md) for the
exact scope and known limitations.

The physical camera adapter accepts the Picamera2-compatible camera at index 0
without a model allowlist. Support is capability-driven, so fixed-focus cameras
can stream without autofocus controls. See the
[camera support roadmap](docs/camera-roadmap.md) for limits and validation.

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
| `container-no-hw-test` | Unit and in-process API tests without device access. |
| `container-hw-test` | Combined GPIO and camera tests on physical Raspberry Pi hardware. |

Build and run the non-hardware test image with:

```shell
make no-hw-test-docker
```

This test image runs pytest. It does not start Uvicorn, publish an HTTP port, or
access Raspberry Pi devices.

## API overview

All public application endpoints use the `/api/v1` prefix. Pin numbers are
Broadcom GPIO numbers (BCM), not physical header positions.

| Method | Path | Purpose |
| --- | --- | --- |
| `GET` | `/api/v1/health` | Check process readiness. |
| `GET` | `/api/v1/camera` | Inspect camera state, effective stream, settings, and telemetry. |
| `GET` | `/api/v1/camera/capabilities` | Inspect runtime-discovered sensor modes and controls. |
| `PATCH` | `/api/v1/camera/settings` | Atomically update supported camera settings. |
| `POST` | `/api/v1/camera/autofocus` | Run one-shot autofocus when advertised. |
| `GET` | `/api/v1/camera/stream` | Consume the shared MJPEG stream. |
| `GET` | `/api/v1/camera/image` | Read the latest encoded JPEG. |
| `GET` | `/api/v1/gpio` | Inspect the backend and complete open-pin registry. |
| `GET` | `/api/v1/gpio/{pin}` | Inspect one open pin. |
| `PUT` | `/api/v1/gpio/{pin}/configuration` | Configure or reconfigure input, output, or PWM mode. |
| `GET` | `/api/v1/gpio/{pin}/value` | Read a digital input, opening it when needed. |
| `PUT` | `/api/v1/gpio/{pin}/value` | Write a digital output, opening it when needed. |
| `PUT` | `/api/v1/gpio/{pin}/pwm` | Set PWM duty cycle and optional frequency. |
| `DELETE` | `/api/v1/gpio/{pin}` | Close and release a pin. |

Swagger contains the complete request and response schemas, examples for every
supported value, and documented error responses.

Expected failures share one response envelope containing a stable `code`, a
human-readable `message`, and optional structured `details`:

| Status | Code | Meaning |
| --- | --- | --- |
| `404` | `not_found` | A required application resource does not exist. |
| `409` | `conflict` | The request conflicts with the current resource state. |
| `422` | `invalid_request` | Input is invalid or a requested capability is unsupported. |
| `503` | `hardware_unavailable` | A camera, GPIO device, or provider cannot complete the operation. |
| `504` | `operation_timeout` | A hardware operation exceeded its deadline. |

Messages and details identify the component, pin, provider, operation, or
validation fields involved. Unexpected software failures remain opaque `500`
responses rather than exposing internal exception text.

Input values are electrical levels: `true` is HIGH and `false` is LOW,
regardless of pull direction. A no-pull input needs an external pull or driven
signal for a stable physical value.

## Runtime configuration

| Environment variable | Values | Default | Meaning |
| --- | --- | --- | --- |
| `EDGE_HARDWARE_SERVICE_BACKEND` | `simulation`, `rpi` | `simulation` | Select the portable in-memory or physical GPIO backend. |

The simulation backend is a supported client-development mode, not a test
mock. It keeps GPIO state and loops a deterministic 1280x720 MJPEG fixture
without importing Raspberry Pi packages. It does not simulate electrical
circuits, optical quality, or arbitrary camera resolutions.

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
                GpioService          CameraService
             (pin ownership)      (stream and policy)
                    |                     |
          GpioDeviceFactory          CameraDevice
               /       \               /      \
       GPIO Zero    Simulation     Picamera2  Simulation
              Raspberry Pi          macOS / Linux / CI
```

The API layer validates HTTP data; services own lifecycle and policy; adapters
isolate physical providers from deterministic simulation. Raspberry Pi imports
stay entirely outside the simulation startup path. See
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
make deploy
```

Both commands explain their behavior, and deployment prompts for the Raspberry
Pi SSH host and confirmation before replacing the existing
`edge-hardware-service` container. `make build` creates the ARM64 `runtime`
image, replaces the local `edge-hardware-service-dev` simulation container,
publishes port 8000, prints the Swagger and ReDoc URLs, and stays attached to
the terminal until Ctrl+C stops and removes it. `make deploy` transfers that
image to the Pi and waits for the remote health endpoint. The remote health
check does not exercise GPIO pins or camera endpoints. This is a manual
development workflow, not a production release mechanism.

## Testing on Raspberry Pi hardware

No external components or wiring are required for the current GPIO validation.
The selected input, digital-output, and PWM pins must be distinct, unconnected,
and unused by another process or peripheral.

Synchronize the current checkout to the Pi, recreate its native virtual
environment, and run the combined GPIO and camera hardware suite:

```shell
make hw-test
```

Then run the same GPIO and camera hardware coverage inside the combined ARM64
test image:

```shell
make hw-test-docker
```

Each hardware command prompts for the SSH host, three distinct unconnected BCM
pins, and confirmation that the camera at index 0 is available. `make hw-test`
also copies the repository with `scripts/sync-repo-to-pi.sh`, deletes and
recreates the remote `.venv`, removes stale non-excluded files from the remote
checkout, and verifies Raspberry Pi OS hardware-library imports before testing.
The GPIO suite verifies internal pull-up/down input
behavior, digital output state, PWM configuration, provider selection, and safe
cleanup. The camera suite discovers the active device's modes and focus controls
and exercises only advertised features. These tests do not measure physical
voltage or waveform accuracy and do not call the deployed HTTP API.

## Development and testing

Python 3.11 and [uv](https://docs.astral.sh/uv/) are required. Start with
`make help`: it lists every supported test command, its required environment,
the inputs it will request, and whether it accesses hardware. The Makefile is a
convenience interface for testing; code-quality tools can still be run directly.

```shell
uv sync
make no-hw-test
```

### Test commands

| Command | What it runs | What a pass proves | What it does not prove |
| --- | --- | --- | --- |
| `make no-hw-test` | All pytest tests except those marked `rpi`, using the local uv environment. This covers unit tests, simulation adapters, service policy, error contracts, and in-process FastAPI requests. | Portable application behavior works on the current development machine. | Raspberry Pi OS packages, the container image, Uvicorn as a running service, GPIO electrical behavior, or a physical camera. |
| `make no-hw-test-docker` | Builds the ARM64 Bookworm `container-no-hw-test` image and runs the non-hardware pytest selection inside it. | The test image builds and the software suite works with its packaged Python and Raspberry Pi OS dependencies. | Device access, a running HTTP server, the production `runtime` image, or physical GPIO/camera behavior. |
| `make hw-test` | Prompts for a Pi SSH host and three safe BCM pins, mirrors the checkout, recreates the remote `.venv`, then runs only the native GPIO and camera tests marked `rpi`. | The native Raspberry Pi OS providers can access the selected real GPIO pins and camera features exercised by the suite. | Container access, the deployed runtime HTTP API, voltage levels, PWM waveform accuracy, or unadvertised camera capabilities. |
| `make hw-test-docker` | Builds the ARM64 `container-hw-test` image, transfers it to the Pi, checks native/container GPIO-provider parity, and runs the marked GPIO and camera tests with privileged device access. | The hardware test image can access the validated GPIO and camera hardware using the expected provider. | The production `runtime` image, deployed HTTP endpoints, voltage levels, PWM waveform accuracy, or other Pi/camera combinations. |

`make build` and `make deploy` are not test suites. `make build` runs the
production-shaped image locally with the simulation backend on port 8000;
`make deploy` starts it remotely with the Raspberry Pi backend and checks its
health endpoint. Neither command proves that physical GPIO or camera endpoints
work.

### CI and manual hardware validation

GitHub-hosted Actions coverage is intentionally limited to the no-hardware
tests. A green GitHub Actions run demonstrates the portable software behavior;
it does not demonstrate that GPIO, Picamera2, device permissions, or provider
selection work on a Raspberry Pi.

Both hardware targets require deliberate, manual validation on a physical
Raspberry Pi. Run them before recording a Pi, camera, or OS combination as
validated. They prompt for the target and pins rather than reading hidden
environment files, and the deployed service container must be stopped so it
does not already own the devices.

The Docker hardware test is relatively slow. `make hw-test-docker` builds an
ARM64 image, exports the complete image, compresses it, copies it to the Pi over
SSH, and loads it into the Pi Docker daemon before tests begin. Building ARM64
on a non-ARM development machine may also use emulation. The transfer can take
several minutes, especially over Wi-Fi; this is expected and is substantially
heavier than syncing the source tree for `make hw-test`.

### Optional local code-quality checks

Install the repository's fast commit hooks once per clone:

```shell
uv run pre-commit install
```

Run formatting and lint checks directly when needed:

```shell
uv run ruff check .
uv run ruff format --check .
uv run pre-commit run --all-files
```

Pre-commit checks basic file hygiene, YAML/TOML validity, Python lint rules,
import ordering, and Ruff formatting. Raspberry Pi tests remain opt-in and are
not run by commit hooks.

## DevOps

### Normal commits and pull requests

Development changes use ordinary branches and pull requests into `main`.
Every branch push and pull request runs formatting, linting, and the complete
non-hardware test suite. Pull requests targeting `main`, and commits that land
on `main`, additionally build the production `runtime` image and require its
`/api/v1/health` smoke test to pass. These CI builds are validation artifacts;
they do not create Git tags, GitHub Releases, or published GHCR images.

Raspberry Pi GPIO and camera tests remain manual because GitHub-hosted runners
do not provide the required physical devices.

### Release candidates and stable releases

Releases start with a version-only pull request. GitHub CLI must be installed
and authenticated locally, and `main` must be clean and exactly match
`origin/main`.

Create a release candidate with a PEP 440 `rcN` version:

```shell
make rc VERSION=0.1.0rc1
```

Promote a tested candidate to a stable release with:

```shell
make release VERSION=0.1.0
```

Each command creates a `release/v<version>` branch, updates `pyproject.toml`
and `uv.lock`, runs pre-commit and non-hardware tests, commits the version
change, pushes only the release branch, and opens a pull request into `main`.
It never pushes directly to `main` and never creates a tag locally.

Merging the release PR is the authorization to publish. A `main` workflow
detects the project-version change, validates the release again, builds and
smoke-tests the runtime image, and then creates the immutable `v<version>` tag.
It publishes the exact image before creating the GitHub Release.

| Version | GitHub Release | GHCR image |
| --- | --- | --- |
| `0.1.0rc1` | Prerelease `v0.1.0rc1` | `ghcr.io/rasmushaa/edge-hardware-service:0.1.0rc1-bookworm` |
| `0.1.0` | Stable release `v0.1.0` | `ghcr.io/rasmushaa/edge-hardware-service:0.1.0-bookworm` |

Stable releases also update
`ghcr.io/rasmushaa/edge-hardware-service:latest-bookworm`; release candidates
never move that alias. The latest stable GitHub Release is always available at
<https://github.com/rasmushaa/edge-hardware-service/releases/latest>.

The release workflow treats the tag, exact image, and GitHub Release as
separate state. Rerunning a partially failed release creates only missing
artifacts. An existing tag on another commit is a hard failure, and immutable
version tags are never moved or overwritten.

## Raspberry Pi troubleshooting

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

Release candidates use PEP 440 versions such as `0.1.0rc1`; stable versions use
`MAJOR.MINOR.PATCH`. Every release publishes an immutable exact image tag such
as `0.1.0rc1-bookworm` or `0.1.0-bookworm`. Stable releases additionally move
`latest-bookworm` to the highest stable version. Prereleases never move it.

Consumers should use an exact image tag for reproducible deployments. Release
tags are created only by the release workflow after a version PR is merged;
they are never created by ordinary CI or moved to another commit.

## Documentation

This project is licensed under the permissive [MIT License](LICENSE).
