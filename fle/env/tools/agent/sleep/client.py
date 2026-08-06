import threading

from fle.env.tools import Tool


class Sleep(Tool):
    # Thread-local storage for tracking accumulated sleep durations per step
    _local = threading.local()

    def __init__(self, connection, game_state):
        super().__init__(connection, game_state)

    @classmethod
    def reset_step_sleep_duration(cls):
        """Reset the accumulated sleep duration for a new step. Call before each step."""
        cls._local.step_sleep_duration = 0.0

    @classmethod
    def get_step_sleep_duration(cls) -> float:
        """Get the accumulated sleep duration for the current step in seconds."""
        return getattr(cls._local, "step_sleep_duration", 0.0)

    @classmethod
    def _add_sleep_duration(cls, duration: float):
        """Add to the accumulated sleep duration for the current step."""
        if not hasattr(cls._local, "step_sleep_duration"):
            cls._local.step_sleep_duration = 0.0
        cls._local.step_sleep_duration += duration

    def __call__(self, seconds: int) -> bool:
        """
        Sleep for up to 15 seconds before continuing. Useful for waiting for actions to complete.
        :param seconds: Number of seconds to sleep.
        :return: True if sleep was successful.
        """
        # Track elapsed ticks for appropriate sleep calculation
        ticks_before = self.game_state.instance.get_elapsed_ticks()

        # Update elapsed ticks on server
        _, _ = self.execute(seconds)

        # Advance simulated time to match the elapsed ticks
        ticks_after = self.game_state.instance.get_elapsed_ticks()
        ticks_added = ticks_after - ticks_before
        if ticks_added > 0:
            real_world_sleep = self.game_state.instance.wait_ticks(ticks_added)
            # Track the accumulated sleep duration for this step
            Sleep._add_sleep_duration(real_world_sleep)

        return True
