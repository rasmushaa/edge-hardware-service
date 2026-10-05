# Repository Productization Guide for Codex

## Purpose

This document is a **design and productization checklist** for the Raspberry Pi hardware adapter API repository.

It is **not a strict implementation specification**. Codex should use this as guidance when evolving the repository and should only implement items that make sense for the current project maturity.

The primary goal is:

> When someone lands on the GitHub repository for the first time, the project should immediately look like a legitimate, usable, maintained software product rather than a hobby code dump.

The repository is intended to act both as:

1. A usable Raspberry Pi hardware adapter service.
2. A professional portfolio project demonstrating production-minded full-stack / ML / data engineering skills.

The **container image is the primary deployable product**. The repository source code supports that product.

---

# 1. Optimize the GitHub First Impression

A visitor should understand the project within roughly 30 seconds.

The top of the README should answer:

- What is this?
- Why does it exist?
- What problem does it solve?
- What hardware/features does it expose?
- What API version is current?
- Which Raspberry Pi OS/runtime image should I pull?
- How do I start it?
- Where are the API docs?
- Can I run it without Raspberry Pi hardware?

Prefer a concise product-style introduction such as:

> Containerized HTTP adapter for Raspberry Pi camera and GPIO hardware.  
> Develop applications against a stable API without coupling the application environment to Raspberry Pi OS hardware dependencies.

Avoid opening the README with:

- Python setup instructions
- repository internals
- dependency management
- long motivation text
- low-level Raspberry Pi troubleshooting

Those belong later in the documentation.

---

# 2. README Suggested Structure

Consider keeping the README in approximately this order:

1. Project title
2. One- or two-sentence product description
3. Status badges
4. Quick start
5. Supported container images
6. API overview
7. Mock/local development
8. Architecture overview
9. Documentation links
10. Development instructions
11. Release/versioning policy
12. License/contributing information

The README should primarily serve **users of the service**.

Detailed contributor and implementation documentation should live under `docs/`.

---

# 3. Professional Repository Badges

Consider a small number of useful badges.

Good candidates:

- CI status
- container build status
- pre-commit status
- license
- current API major version
- GHCR/container package link
- optional test coverage

Avoid excessive badge clutter.

The message should be:

> tested · packaged · documented · versioned

not simply that the repository has many badges.

---

# 4. Treat the Container Image as the Main Product Artifact

This project is deployed as a service, so Docker images are more important than the Python package version alone.

Keep three concepts separate:

## API version

Example:

```text
/api/v1
/api/v2
```

Represents the public HTTP contract.

## Service release

Example:

```text
1.4.2
```

Represents the software release.

## Runtime / Raspberry Pi OS variant

Example:

```text
bookworm
trixie
```

Represents the hardware/runtime dependency environment.

A release image could therefore look like:

```text
ghcr.io/<owner>/rpi-hardware-service:1.4.2-bookworm
```

---

# 5. Consider a Simple Image Tagging Policy

Potential tag structure:

```text
1.4.2-bookworm   # immutable exact release
1.4-bookworm     # latest compatible 1.4.x
1-bookworm       # latest API/service major v1
```

Equivalent variants may exist for other supported Raspberry Pi OS versions.

Example:

```text
1.4.2-trixie
1.4-trixie
1-trixie
```

Avoid relying only on:

```text
latest
```

If `latest` exists, document exactly what it means.

For reproducible deployment, recommend immutable tags.

For convenient deployment within one API major, recommend tags such as:

```text
1-bookworm
```

---

# 6. Do Not Mutate Old Immutable Image Tags

A tag such as:

```text
1.4.2-bookworm
```

should always represent the same release artifact.

If:

- base image changes
- apt dependencies change
- Picamera2/libcamera packages change
- runtime dependencies change
- application code changes

publish a new service release instead.

For example:

```text
1.4.3-bookworm
```

The container is part of the released software product.

---

# 7. Consider a Machine-Readable Supported Image Matrix

A file such as:

```text
release/images.yaml
```

could define supported image/runtime variants.

Example:

```yaml
service_major: 1
api_version: v1

variants:
  - name: bookworm
    status: stable
    platform: linux/arm64
    python: "3.11"

  - name: trixie
    status: preview
    platform: linux/arm64
    python: "3.13"
```

This file could eventually be used by:

- CI
- Docker build matrix
- release workflow
- documentation generation
- compatibility documentation

The goal is to prevent documentation and build configuration from drifting apart.

Do not add this abstraction unless it simplifies the project.

---

# 8. Supported Image Documentation

The README should show the **currently supported image families**, not every historical image.

Example:

| API | Runtime | Status | Recommended tag |
|---|---|---|---|
| v1 | Bookworm | Stable | `1-bookworm` |
| v1 | Trixie | Preview | `1-trixie` |

Historical versions should preferably be discoverable through:

- GitHub Releases
- GHCR package versions
- release notes

Avoid filling the README with dozens of old image tags.

---

# 9. Automated Release Metadata

For tagged releases, consider automatically generating release information containing:

- service version
- API version
- supported runtime variants
- exact image tags
- image digests
- source commit
- notable changes
- pull commands

Example:

```markdown
## Images

| Runtime | Image | Digest |
|---|---|---|
| Bookworm | `ghcr.io/...:1.4.2-bookworm` | `sha256:...` |
| Trixie | `ghcr.io/...:1.4.2-trixie` | `sha256:...` |
```

Prefer generating this from actual successful build outputs instead of manually maintaining it.

---

# 10. Release Workflow Concept

A tag-based release could eventually follow:

```text
Git tag
  ↓
tests
  ↓
build runtime variants
  ↓
container smoke tests
  ↓
push immutable images
  ↓
collect image digests
  ↓
publish GitHub Release
  ↓
update/generated docs where appropriate
```

Not all stages need to exist in the first version.

The project should stay maintainable by one person.

---

# 11. OCI Container Metadata

Consider adding standard OCI metadata to released images.

Useful fields include:

```text
org.opencontainers.image.title
org.opencontainers.image.description
org.opencontainers.image.source
org.opencontainers.image.documentation
org.opencontainers.image.version
org.opencontainers.image.revision
org.opencontainers.image.licenses
```

This allows users to inspect a container and determine:

- what it is
- which release it contains
- which Git revision produced it
- where the source lives
- where the documentation lives

---

# 12. Runtime Version / Metadata Endpoint

Consider exposing deployment metadata through the service.

Potential endpoints:

```text
GET /health
GET /version
GET /capabilities
```

Example `/version` response:

```json
{
  "service": "rpi-hardware-service",
  "service_version": "1.4.2",
  "api_versions": ["v1"],
  "runtime": "bookworm",
  "git_revision": "8cd71f4",
  "camera_backend": "picamera2",
  "gpio_backend": "raspberry_pi"
}
```

Example `/capabilities` response:

```json
{
  "camera": true,
  "gpio": true,
  "pwm": true,
  "mock": false
}
```

This improves runtime traceability and allows downstream services to inspect adapter capabilities.

---

# 13. API Documentation Should Be Highly Visible

FastAPI provides runtime API documentation automatically.

Make the README clearly point users toward:

```text
/docs
/redoc
/openapi.json
```

Also consider exporting OpenAPI during CI or releases into:

```text
docs/api/openapi.json
```

This makes the public API contract visible without requiring a running Raspberry Pi.

---

# 14. API Endpoint Overview in README

Include a concise endpoint overview near the top of the repository.

Do not duplicate the full OpenAPI schema.

Example:

```text
System
GET  /health
GET  /version
GET  /capabilities

Camera
GET  /api/v1/camera/status
GET  /api/v1/camera/stream
GET  /api/v1/camera/settings
PATCH /api/v1/camera/settings

GPIO
GET  /api/v1/gpio/{pin}
PUT  /api/v1/gpio/{pin}
POST /api/v1/gpio/{pin}/pwm
```

The exact endpoints should always follow the actual implementation.

---

# 15. Consider OpenAPI Contract Checks

As the project matures, consider making accidental public API changes visible.

Possible process:

```text
FastAPI application
      ↓
generate OpenAPI
      ↓
compare with committed/released contract
      ↓
detect unexpected API changes
```

This could be especially valuable when multiple API major versions eventually exist.

Do not create unnecessary complexity in early versions.

---

# 16. Mock Mode Should Be a First-Class Feature

The ability to run the adapter without Raspberry Pi hardware is one of the project's strongest features.

Make this visible in the README.

Example message:

> The same HTTP contract can be used with Raspberry Pi hardware or a mock backend for development on macOS/Linux.

Provide a very small quick-start example.

For example:

```bash
docker run   -e HARDWARE_BACKEND=mock   -p 8080:8080   ghcr.io/<owner>/rpi-hardware-service:1-bookworm
```

The exact configuration should match the implemented design.

The mock backend should not feel like an internal testing hack.

It is part of the development experience.

---

# 17. Architecture Diagram

Include a small architecture diagram in the README or documentation.

For example:

```text
                 HTTP API v1
                     │
           ┌─────────┴─────────┐
           │                   │
     Camera interface      GPIO interface
           │                   │
      ┌────┴────┐         ┌────┴────┐
      │         │         │         │
  Picamera2    Mock      RPi GPIO   Mock
      │                     │
      └──── Raspberry Pi ───┘
```

This should communicate the important boundary:

> Application developers consume the HTTP API and do not depend directly on Raspberry Pi OS camera/GPIO libraries.

---

# 18. Suggested Documentation Structure

Consider maintaining:

```text
docs/
├── getting-started.md
├── images.md
├── compatibility.md
├── architecture.md
├── development.md
├── releases.md
└── api/
    └── openapi.json
```

Possible responsibilities:

### `getting-started.md`

- pull image
- start service
- first API request
- API docs URL

### `images.md`

- available image families
- tag policy
- stable vs preview variants
- immutable tags

### `compatibility.md`

- Raspberry Pi models
- Raspberry Pi OS versions
- camera stack
- architectures
- known limitations

### `architecture.md`

- service boundaries
- hardware interfaces
- mock architecture
- why this service exists

### `development.md`

- uv setup
- pre-commit
- tests
- local mock mode
- Docker development

### `releases.md`

- SemVer policy
- API versioning
- image tags
- release procedure

---

# 19. Suggested Repository Files

Possible professional repository structure:

```text
README.md
LICENSE
CHANGELOG.md
SECURITY.md
CONTRIBUTING.md
Makefile
pyproject.toml
uv.lock
.pre-commit-config.yaml

src/
tests/
docker/
docs/
scripts/
release/

.github/
└── workflows/
    ├── ci.yml
    ├── container.yml
    ├── release.yml
    └── docs.yml
```

Do not add empty files or workflows purely for appearance.

Each file should exist only when it provides real value.

---

# 20. CI Quality Signals

On normal pull requests, consider validating some combination of:

```text
formatting/linting
type checking
unit tests
integration tests
OpenAPI generation/contract check
Docker build
mock container startup
HTTP smoke tests
```

A useful principle:

> Test the deployable container, not only the Python functions.

For example, a smoke test could:

1. build/start the container in mock mode
2. wait for `/health`
3. call several representative API endpoints
4. verify expected HTTP responses
5. stop the container

This gives significantly stronger confidence than unit tests alone.

---

# 21. Hardware Tests Are Different From CI Tests

Do not pretend standard GitHub CI validates physical Raspberry Pi hardware.

Clearly distinguish:

## Automated software/container tests

Can run on GitHub-hosted infrastructure.

## Hardware compatibility validation

Requires a physical Raspberry Pi, camera, GPIO, etc.

A compatibility matrix may eventually say:

```text
Raspberry Pi 5 + Bookworm + Camera Module 3 → tested
Raspberry Pi 4 + Bookworm → tested
Trixie → experimental
```

Only mark combinations as tested when actually tested.

---

# 22. Future: Physical Pi Release Validation

A later portfolio enhancement could be a self-hosted Raspberry Pi CI runner.

Possible release flow:

```text
software tests
     ↓
ARM image build
     ↓
release candidate deployed to physical Pi
     ↓
camera/GPIO smoke tests
     ↓
publish stable release
```

This is intentionally a future option.

Do not make the project dependent on this infrastructure early.

---

# 23. Consider SBOM and Build Provenance

As the project matures, Docker releases may include:

- SBOM
- build provenance/attestations
- image digests

This is a useful software supply-chain feature and a good professional signal.

It should remain low-maintenance.

Avoid security theatre or large infrastructure solely for portfolio appearance.

---

# 24. Pre-commit

Use pre-commit where it improves repository quality.

Possible hooks:

- Ruff formatting/linting
- whitespace cleanup
- YAML validation
- TOML validation
- end-of-file fixes
- optional type/test checks where fast enough

The README may include a pre-commit/CI status badge if useful.

Keep local commit hooks fast enough that developers do not disable them.

---

# 25. Changelog and Release Notes

Consider maintaining a `CHANGELOG.md`.

Focus on changes that affect users:

- new API endpoints
- API behavior changes
- supported hardware changes
- runtime image changes
- Raspberry Pi OS support
- dependency/runtime changes
- bug fixes

Do not fill the changelog with internal refactoring details unless they affect users.

GitHub Releases may contain the detailed release-specific artifact information.

---

# 26. Compatibility Matrix

A clear compatibility page can add significant credibility.

Potential dimensions:

| Pi | OS | Architecture | Camera | Status |
|---|---|---|---|---|
| Pi 5 | Bookworm | arm64 | Camera Module 3 | Tested |
| Pi 4 | Bookworm | arm64 | TBD | Supported |
| Pi 5 | Trixie | arm64 | TBD | Preview |

Never claim support that has not been verified or intentionally designed.

---

# 27. Keep the Project Small Enough to Maintain

Professional does not mean enterprise-sized.

Avoid adding technologies merely to show them on the portfolio.

Examples of unnecessary complexity for this project may include:

- Kubernetes
- elaborate release orchestration
- external databases
- service meshes
- heavy documentation platforms
- excessive microservices
- unnecessary package registries

Prefer:

```text
FastAPI
Docker
GitHub Actions
GHCR
pytest
pre-commit
OpenAPI
simple scripts/config
```

The strength of the portfolio project should come from clean boundaries and good engineering decisions.

---

# 28. Portfolio Signals This Repository Can Demonstrate

The project should naturally demonstrate:

- Python application architecture
- typed HTTP APIs
- FastAPI
- hardware abstraction
- dependency isolation
- Raspberry Pi / edge deployment
- Docker
- ARM containers
- API versioning
- reproducible releases
- CI/CD
- GitHub Actions
- container registries
- mockable hardware
- integration testing
- API contract documentation
- runtime traceability
- software compatibility management
- deployment artifacts
- release engineering

These should emerge from solving real project problems, not from artificial complexity.

---

# 29. Suggested "Professional First Touch" Checklist

Before a public release, consider whether the repository landing page provides:

- [ ] clear one-sentence description
- [ ] useful badges
- [ ] screenshot/diagram if helpful
- [ ] one-command image pull
- [ ] minimal run command
- [ ] current stable image tag
- [ ] supported OS/runtime matrix
- [ ] API docs link
- [ ] short endpoint summary
- [ ] mock-mode instructions
- [ ] architecture overview
- [ ] license
- [ ] visible release history
- [ ] CI passing
- [ ] reproducible tagged releases

A visitor should not need to inspect the source tree to understand how to use the service.

---

# 30. Suggested Implementation Priority

Codex should not attempt everything at once.

A reasonable order could be:

## Phase 1 — Strong repository landing page

- README restructuring
- product description
- badges
- quick start
- image pull/run commands
- endpoint overview
- mock mode
- simple architecture diagram

## Phase 2 — Release discipline

- clear service/API/image version policy
- GHCR images
- immutable tags
- Git tag release workflow
- GitHub Releases

## Phase 3 — Generated contracts and metadata

- OpenAPI export
- `/version`
- `/capabilities`
- OCI metadata
- image compatibility documentation

## Phase 4 — Stronger release engineering

- multi-runtime build matrix
- generated release image table
- digests
- SBOM/provenance
- hardware compatibility tests
- optional physical Pi CI runner

The current repository maturity should determine which phase is appropriate.

---

# 31. Core Design Principle

When deciding whether to add a feature to this repository, ask:

> Does this make the hardware adapter easier to understand, use, test, deploy, reproduce, or maintain?

If not, it is probably unnecessary.

The desired impression is not:

> This repository uses many technologies.

The desired impression is:

> This is a small product built by someone who understands how production software should be packaged, documented, tested, versioned, and operated.
