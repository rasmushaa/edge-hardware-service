.PHONY: build build-pi-hardware-test deploy format lint pre-commit pi-dev-setup pi-hardware-test pi-container-hardware-test test

build:
	docker buildx build \
		--platform linux/arm64 \
		--target runtime \
		--tag edge-hardware-service:dev \
		--load \
		.

build-pi-hardware-test:
	docker buildx build \
		--platform linux/arm64 \
		--target rpi-hardware-test \
		--tag edge-hardware-service:rpi-hardware-test \
		--load \
		.

deploy:
	@if [ -z "$(PI_HOST)" ]; then \
		echo "Usage: make deploy PI_HOST=user@host" >&2; \
		exit 1; \
	fi
	./scripts/deploy-pi-manual.sh "$(PI_HOST)"

format:
	uv run ruff check --fix .
	uv run ruff format .

lint:
	uv run ruff check .
	uv run ruff format --check .

pre-commit:
	uv run pre-commit run --all-files

test:
	uv run pytest

pi-dev-setup:
	@./scripts/setup-pi-dev.sh

pi-hardware-test:
	@./scripts/run-pi-hardware-tests.sh

pi-container-hardware-test: build-pi-hardware-test
	@./scripts/run-pi-container-hardware-tests.sh
