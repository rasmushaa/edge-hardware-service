.DEFAULT_GOAL := help

.PHONY: help no-hw-test no-hw-test-docker hw-test hw-test-docker build deploy

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
		'                          replace the deployed container, and check /health.' \
		'                          This does not exercise GPIO or camera API operations.'

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
