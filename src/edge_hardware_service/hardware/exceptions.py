
from edge_hardware_service.models.gpio import PinMode


class PinModeConflict(Exception):
    def __init__(self, pin: int, mode: PinMode):
        self.pin = pin
        self.mode = mode
        super().__init__(f"Pin {pin} is not in mode {mode}")