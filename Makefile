.DEFAULT_GOAL := help

.PHONY: help no-hw-test no-hw-test-docker smoke-test hw-test hw-test-docker build deploy rc release

SMOKE_IMAGE ?= edge-hardware-service:dev
SMOKE_ATTEMPTS ?= 30

help:
	@printf '%s\n' \
		'Edge Hardware Service commands' \
		'' \
		'Testing without hardware:' \
		'  make no-hw-test         Run unit and in-process API tests locally.' \
		'                          Raspberry Pi hardware tests are excluded.' \
		'  make no-hw-test-docker  Build the container-no-hw-test image and run the' \
		'                          same non-hardware suite inside its Bookworm image.' \
		'                          This does not start Uvicorn or access devices.' \
		'  make smoke-test         Start SMOKE_IMAGE with the simulation backend and' \
		'                          wait for /api/v1/health to return {"status":"ok"}.' \
		'                          Defaults to edge-hardware-service:dev.' \
		'' \
		'Testing on Raspberry Pi 5 Bookworm hardware:' \
		'  make hw-test            Sync this checkout to the Pi, recreate the remote' \
		'                          .venv, then run native GPIO and camera hardware tests.' \
		'                          Prompts for SSH host, three safe BCM pins, and camera.' \
		'  make hw-test-docker     Build and transfer the ARM64 container-hw-test image,' \
		'                          then run both GPIO and camera hardware tests in it.' \
		'                          Prompts for the same host, pins, and confirmation.' \
		'' \
		'Production-shaped development container:' \
		'  make build              Build edge-hardware-service:dev for linux/arm64,' \
		'                          replace the local simulation container, publish' \
		'                          port 8000, and run attached until Ctrl+C.' \
		'                          This does not run tests or access physical hardware.' \
		'  make deploy             Prompt for a Pi SSH host, transfer that runtime image,' \
		'                          replace the deployed container, and check /api/v1/health.' \
		'                          This does not exercise GPIO or camera API operations.' \
		'' \
		'Opening release pull requests from main:' \
		'  make rc VERSION=0.1.1rc1' \
		'                          Create, validate, push, and open an RC release PR.' \
		'  make release VERSION=0.1.1' \
		'                          Create, validate, push, and open a stable release PR.' \
		'                          The version must be newer than the project and all tags.' \
		'                          Neither command pushes main or creates a tag. Merging the' \
		'                          PR triggers the release GitHub Actions workflow.'

no-hw-test:
	@printf '%s\n' \
		'Running local unit and in-process API tests without hardware.' \
		'Pytest excludes every test marked rpi.'
	uv run pytest

no-hw-test-docker:
	@printf '%s\n' \
		'Building the ARM64 Bookworm non-hardware test image.' \
		'The image runs unit and in-process API tests; it does not start the service.'
	docker buildx build \
		--platform linux/arm64 \
		--target container-no-hw-test \
		--tag edge-hardware-service:container-no-hw-test \
		--load \
		.
	docker run --rm \
		--platform linux/arm64 \
		edge-hardware-service:container-no-hw-test

smoke-test:
	@printf '%s\n' \
		'Starting $(SMOKE_IMAGE) with the simulation backend.' \
		'Waiting for /api/v1/health to report status ok.'
	@set -eu; \
		container_id="$$(docker run --detach \
			--env EDGE_HARDWARE_SERVICE_BACKEND=simulation \
			"$(SMOKE_IMAGE)")"; \
		cleanup() { \
			docker rm --force "$$container_id" >/dev/null 2>&1 || true; \
		}; \
		trap cleanup EXIT INT TERM; \
		attempt=1; \
		while [ "$$attempt" -le "$(SMOKE_ATTEMPTS)" ]; do \
			if health="$$(docker exec "$$container_id" python -c \
				'import json, urllib.request; body = json.load(urllib.request.urlopen("http://127.0.0.1:8000/api/v1/health", timeout=1)); assert body == {"status": "ok"}, body; print(json.dumps(body, separators=(",", ":")))' \
				2>/dev/null)"; then \
				printf 'Health check passed: %s\n' "$$health"; \
				exit 0; \
			fi; \
			if ! docker inspect --format '{{.State.Running}}' "$$container_id" 2>/dev/null \
				| grep -qx true; then \
				break; \
			fi; \
			attempt=$$((attempt + 1)); \
			sleep 1; \
		done; \
		printf '%s\n' 'Health check failed. Container logs:' >&2; \
		docker logs "$$container_id" >&2 || true; \
		exit 1

hw-test:
	@printf '%s\n' \
		'Syncing the repository, recreating the remote .venv, and then running' \
		'native GPIO and camera tests on Raspberry Pi hardware.' \
		'The command will explain requirements and ask for every input.'
	@./scripts/run-pi-hardware-tests.sh

hw-test-docker:
	@printf '%s\n' \
		'Building and running the combined GPIO and camera hardware test image.' \
		'The command will explain requirements and ask for every input.'
	docker buildx build \
		--platform linux/arm64 \
		--target container-hw-test \
		--tag edge-hardware-service:container-hw-test \
		--load \
		.
	@./scripts/run-pi-container-hardware-tests.sh

build:
	@printf '%s\n' \
		'Building the single-worker production-shaped runtime image.' \
		'This creates edge-hardware-service:dev for linux/arm64 and runs no tests.' \
		'Requires Docker Buildx and available local port 8000.' \
		'An existing edge-hardware-service-dev container will be replaced.'
	docker buildx build \
		--platform linux/arm64 \
		--target runtime \
		--tag edge-hardware-service:dev \
		--load \
		.
	@if docker container inspect edge-hardware-service-dev >/dev/null 2>&1; then \
		echo 'Replacing existing local development container...'; \
		docker rm --force edge-hardware-service-dev >/dev/null; \
	fi
	@printf '%s\n' \
		'Starting the attached local container with the simulation backend.' \
		'The API documentation will be available after startup:' \
		'  Swagger UI: http://localhost:8000/docs' \
		'  ReDoc:      http://localhost:8000/redoc' \
		'Press Ctrl+C to stop and remove the container.'
	docker run --rm \
		--name edge-hardware-service-dev \
		--platform linux/arm64 \
		--publish 8000:8000 \
		--env EDGE_HARDWARE_SERVICE_BACKEND=simulation \
		edge-hardware-service:dev

deploy:
	@printf '%s\n' \
		'Deploying edge-hardware-service:dev, built from the runtime target.' \
		'This replaces the named Pi container and verifies /api/v1/health only.'
	@./scripts/deploy-pi-manual.sh

rc:
	@./scripts/create-release-pr.sh rc "$(VERSION)"

release:
	@./scripts/create-release-pr.sh stable "$(VERSION)"
