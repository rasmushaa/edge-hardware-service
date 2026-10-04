# Edge Hardware Service

## Container image

The image uses Debian Bookworm's Python 3.11 and inherits Raspberry Pi Python
packages from the operating system. GPIO Zero, lgpio, libcamera, Picamera2, and
NumPy are installed with `apt`; uv owns only the portable application packages.

Build the production image:

```shell
docker build --tag edge-hardware-service .
```

Simulation is the safe default and needs no hardware devices:

```shell
docker run --rm \
  --publish 8000:8000 \
  edge-hardware-service
```

Select Raspberry Pi hardware at runtime with the repository-specific
`EDGE_HARDWARE_SERVICE_BACKEND` setting:

```shell
docker run --rm \
  --privileged \
  --volume /run/udev:/run/udev:ro \
  --publish 8000:8000 \
  --env EDGE_HARDWARE_SERVICE_BACKEND=rpi \
  edge-hardware-service
```

`--privileged` is the simplest initial hardware-validation configuration because
camera discovery can use several video, media, DMA-heap, GPIO, and udev
interfaces. After validating the target Pi, replace it with explicit `--device`
and group mappings appropriate to that board and attached hardware.

The Dockerfile pins uv and provides two build targets:

- `runtime` is the default production image without development dependencies.
- `container-smoke-test` contains pytest and runs the portable suite by default.

```shell
docker build \
  --target container-smoke-test \
  --tag edge-hardware-service:container-smoke-test \
  .
docker run --rm edge-hardware-service:container-smoke-test
```

### Ad hoc hardware testing during development

Build the ARM64 development image locally:

```shell
make build
```

Deploy it by providing the Pi's SSH destination:

```shell
make deploy PI_HOST=pi@edgepi.local
```

`PI_HOST` is the only deployment parameter. The deployment transfers
`edge-hardware-service:dev` using `docker save | gzip | ssh | docker load`,
replaces the existing `edge-hardware-service` container, enables Raspberry Pi
mode, and waits for the API health check.

After deployment, open `http://edgepi.local:8000/docs` for the interactive API
or verify health and the empty GPIO registry:

```shell
curl http://edgepi.local:8000/api/v1/health
curl http://edgepi.local:8000/api/v1/gpio
```

Configure BCM 17 as a pull-up input. It should read `true` while unconnected and
`false` while connected to a physical ground pin:

```shell
curl --request PUT \
  --header 'Content-Type: application/json' \
  --data '{"mode":"input","pull":"up"}' \
  http://edgepi.local:8000/api/v1/gpio/17/configuration

curl http://edgepi.local:8000/api/v1/gpio/17/value
```

Only test outputs on pins connected to a safe LED-and-resistor circuit or an
appropriate meter. For example, write and then release BCM 22:

```shell
curl --request PUT \
  --header 'Content-Type: application/json' \
  --data '{"value":true}' \
  http://edgepi.local:8000/api/v1/gpio/22/value

curl --request PUT \
  --header 'Content-Type: application/json' \
  --data '{"value":false}' \
  http://edgepi.local:8000/api/v1/gpio/22/value

curl --request DELETE http://edgepi.local:8000/api/v1/gpio/22
```

## Tests

Run the portable service, simulation, and HTTP integration suite with:

```shell
uv run pytest
```

Raspberry Pi hardware smoke tests are excluded by default. Run them only inside
the prepared Bookworm container on a Raspberry Pi, using BCM pins that are safe
to read or drive:

```shell
EDGE_HARDWARE_RPI_INPUT_PIN=17 \
EDGE_HARDWARE_RPI_OUTPUT_PIN=22 \
EDGE_HARDWARE_RPI_PWM_PIN=18 \
uv run pytest -m rpi
```

The Raspberry Pi tests actively toggle the configured output and PWM pins.
