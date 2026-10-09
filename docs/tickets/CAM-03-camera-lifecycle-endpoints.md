# CAM-03: Camera lifecycle services and endpoints

Status: TODO.

## Context

The camera is currently created once during application startup and released
only during application shutdown. If startup fails, a transient libcamera error
occurs, or a camera is physically replaced, the user must restart the complete
service to make another connection attempt. That unnecessarily interrupts GPIO
and other unrelated hardware services.

Add explicit camera lifecycle operations so clients can restore defaults,
release camera ownership, connect an attached camera, or rebuild the current
connection without restarting the process.

## API

### Reset settings

```http
POST /api/v1/camera/settings/reset
```

Atomically apply `DEFAULT_CAMERA_SETTINGS` to the connected camera and return
`200 OK` with `CameraStatus`. This is a settings operation only: it must not
replace the Picamera2 instance when the provider can apply the defaults through
normal reconfiguration. Existing rollback behavior applies if reset fails.

The defaults are provider-managed FPS and sensor mode, 1280x720 output, zero
rotation, and unmanaged focus.

### Release camera

```http
DELETE /api/v1/camera
```

Stop recording, close Picamera2, release all camera resources, end active MJPEG
streams, discard buffered frames, and delete the active settings. Return
`204 No Content`. Repeated release requests are idempotent.

Status remains available after release and reports a new `disconnected` state,
with `settings`, `stream`, telemetry, model, and active device index set to
`null`. An intentionally released camera is not `unavailable`: that state is
reserved for failed connection or operation attempts.

### Connect camera

```http
POST /api/v1/camera/connect
Content-Type: application/json

{
  "device_index": 0
}
```

Create a new camera adapter for the requested Picamera2 index, apply default
settings, start streaming, and return `201 Created` with `CameraStatus` only
after the first complete frame arrives. `device_index` defaults to `0` when
omitted. Camera enumeration is not part of this ticket; callers select a known
index or use the default.

Connecting while a camera is already starting, streaming, or reconfiguring
returns `409 Conflict` and does not replace it. The caller must explicitly
release or reconnect instead. A failed open/configure/start attempt returns the
existing `503 hardware_unavailable` envelope, leaves no partially owned device,
and records the attempted index and failure reason for status and retry.

### Reconnect camera

```http
POST /api/v1/camera/reconnect
```

Serialize one recovery operation that stops and closes the current adapter,
creates a new adapter for the current or last-attempted device index, reapplies
the last requested settings, and waits for the first complete frame. Return
`200 OK` with `CameraStatus` on success.

Reconnect differs deliberately from `DELETE` followed by `connect`: it retains
the requested settings across replacement. If no settings have ever been
successfully applied, reconnect uses `DEFAULT_CAMERA_SETTINGS`. If the saved
settings are unsupported by a physically replaced camera, retry once with
defaults and report in status that defaults were used. Do not silently retain a
partial subset of the saved settings.

A failed reconnect cannot roll back to the old adapter because it has already
been released. It returns `503 hardware_unavailable`, transitions to
`unavailable`, preserves the desired settings for inspection and another retry,
and closes any partially created replacement adapter.

## Service design

- Give `CameraService` an adapter factory rather than only a constructed device
  so it can create a fresh Picamera2 instance after release or failure.
- Keep the selected/last-attempted device index independently from the live
  adapter so reconnect remains possible while unavailable.
- Replace or reopen the frame broker as part of connect/reconnect. Wake and end
  consumers attached to the previous generation; clients may establish a new
  MJPEG request after the operation succeeds.
- Serialize connect, reconnect, release, settings updates, and autofocus under
  one lifecycle lock. Expose transitional `starting`, `reconfiguring`, or a new
  `reconnecting` state so status calls remain informative.
- Never publish callbacks from an old adapter generation into the new broker.
  A generation token or equivalent ownership check should reject late frames.
- Ensure every failed construction or startup path closes the partially created
  adapter exactly once.
- Implement the same lifecycle contract in simulation so API tests remain
  deterministic.

These operations reopen the software connection; they do not power-cycle the
sensor or force the operating system to discover hardware that is absent from
libcamera.

## Errors and state

- Add a stable `camera_not_connected` error with HTTP 409 for operations that
  require a camera after an intentional release.
- Continue using `hardware_unavailable` with HTTP 503 when connection was
  attempted but the provider could not open or start the camera.
- `GET /api/v1/camera` always succeeds and distinguishes `disconnected` from
  `unavailable`.
- `GET /capabilities`, settings updates, autofocus, image, and stream return
  `camera_not_connected` while disconnected.
- Reset settings is valid only for a connected camera. Reconnect is valid while
  streaming or unavailable, including after a failed application-startup
  connection attempt.

## Acceptance criteria

- Reset restores all defaults atomically and rolls back the complete previous
  settings when provider reconfiguration fails.
- Release stops encoding, closes the provider exactly once, clears settings and
  frames, ends stream consumers, and is idempotent.
- Connect after release creates a fresh adapter and does not require an
  application restart.
- Reconnect creates a new adapter instance, preserves settings when compatible,
  and produces a new frame before reporting success.
- Reconnect from startup `unavailable` state retries the saved device index.
- Replacing the physical camera between release and connect updates model,
  capabilities, applied stream information, and telemetry without retaining
  data from the old camera.
- Concurrent lifecycle and camera-control calls have deterministic conflict or
  serialization behavior and cannot leak adapters or cross camera generations.
- Failure tests cover open, capability discovery, configuration, encoder start,
  first-frame timeout, close, and reconnect-default fallback.
- OpenAPI, README, and camera design documentation describe all four operations
  and clearly distinguish reset, release, connect, and reconnect.
