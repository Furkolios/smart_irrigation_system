from enum import Enum
import logging
from typing import List
from datetime import datetime


class SystemState(str, Enum):
    BOOTING = "BOOTING"
    READY = "READY"
    RUNNING = "RUNNING"
    DEGRADED = "DEGRADED"
    ERROR = "ERROR"
    SHUTDOWN = "SHUTDOWN"


class StateManager:
    """
    Manages the global state of the irrigation system.
    """

    def __init__(self):
        self._current_state = SystemState.BOOTING
        self._last_state_change = datetime.now()
        self._errors: List[str] = []
        self.logger = logging.getLogger("state_manager")
        self.logger.info(f"System State initialized: {self._current_state}")

    @property
    def current_state(self) -> SystemState:
        return self._current_state

    def transition_to(self, new_state: SystemState, reason: str = ""):
        """Transition to a new state."""
        if self._current_state != new_state:
            old_state = self._current_state
            self._current_state = new_state
            self._last_state_change = datetime.now()
            self.logger.info(
                f"State transition: {old_state} -> {new_state} | Reason: {reason}"
            )

    def report_error(self, error_msg: str, critical: bool = False):
        """Report an error. If critical, transitions to ERROR state."""
        timestamp = datetime.now().isoformat()
        full_msg = f"[{timestamp}] {error_msg}"
        self._errors.append(full_msg)
        self.logger.error(f"System Error: {error_msg}")

        if critical:
            self.transition_to(SystemState.ERROR, reason=error_msg)
        elif self._current_state != SystemState.ERROR:
            # Non-critical errors might degrade the system
            self.transition_to(
                SystemState.DEGRADED, reason=f"Non-critical error: {error_msg}"
            )

    def clear_errors(self):
        """Clear error history and attempt to reset state to READY."""
        self._errors.clear()
        if self._current_state in [SystemState.ERROR, SystemState.DEGRADED]:
            self.transition_to(SystemState.READY, reason="Errors cleared")

    def get_status(self) -> dict:
        return {
            "state": self._current_state.value,
            "last_change": self._last_state_change.isoformat(),
            "active_errors": len(self._errors),
            "recent_errors": self._errors[-5:],
        }
