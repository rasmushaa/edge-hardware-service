"""Domain exceptions for camera lifecycle and operations."""


class CameraError(RuntimeError):
    """Base class for expected camera failures."""


class CameraUnavailable(CameraError):
    """The selected camera could not be initialized or is not available."""


class CameraNotReady(CameraError):
    """No complete camera frame became available before the deadline."""


class CameraOperationError(CameraError):
    """A camera control or reconfiguration operation failed."""


class CameraSettingsInvalid(CameraError, ValueError):
    """A settings update conflicts with the active sensor configuration."""


class CameraCapabilityUnsupported(CameraSettingsInvalid):
    """The active camera does not implement a requested feature."""


class CameraAutofocusTimeout(CameraOperationError, TimeoutError):
    """Autofocus did not complete within its fixed timeout."""
