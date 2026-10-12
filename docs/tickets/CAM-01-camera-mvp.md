# CAM-01: Capability-driven Picamera2 camera MVP

Status: implemented in the pre-release API. The current design supersedes the
original IMX708-only proposal.

## Outcome

- One process-scoped camera at Picamera2 index 0.
- Runtime control discovery without a model allowlist.
- Provider-selected sensor modes with requested and applied sizes reported
  separately.
- Provider-managed sensor, frame-rate, and focus defaults.
- Independent requested sensor and encoded-output resolutions.
- Shared 1280x720-by-default MJPEG stream and latest-image endpoint.
- Atomic settings updates with rollback.
- Optional autofocus, manual focus, continuous focus, and telemetry.
- Stable capability errors for well-formed unsupported requests.
- Deterministic simulation and opt-in native/container hardware suites.

The maintained behavior, limits, and validation commands are documented in
[`docs/camera-roadmap.md`](../camera-roadmap.md).
