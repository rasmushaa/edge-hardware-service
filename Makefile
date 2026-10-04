.PHONY: build deploy

build:
	docker buildx build \
		--platform linux/arm64 \
		--target runtime \
		--tag edge-hardware-service:dev \
		--load \
		.

deploy:
	@if [ -z "$(PI_HOST)" ]; then \
		echo "Usage: make deploy PI_HOST=user@host" >&2; \
		exit 1; \
	fi
	./scripts/deploy-pi-manual.sh "$(PI_HOST)"
