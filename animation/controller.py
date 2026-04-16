"""
In-game lifecycle controller for live builds.

Uses a trigger scoreboard objective so the player can request rebuild actions
without leaving Minecraft. Supported controls:

- ``/trigger animctl set 1``: clear current build area and forget sticky origin
- ``/trigger animctl set 2``: build using the configured source; this reuses the
  sticky origin if one exists, otherwise it resolves a fresh player-relative one
- ``/trigger animctl set 3``: apply configured modify/decay stages in-place
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from typing import Any

from gdpc import interface


@dataclass(frozen=True, slots=True)
class LifecycleAction:
    kind: str


class BuildLifecycleController:
    def __init__(self, host: str, objective: str = "animctl") -> None:
        self.host = host
        self.objective = objective
        self._setup_done = False

    def setup(self) -> None:
        if self._setup_done:
            return
        self._run_command_allowing_expected_errors(
            f"scoreboard objectives add {self.objective} trigger",
            allowed_substrings=["already exists"],
        )
        self._run_command_allowing_expected_errors(
            f"scoreboard players enable @a {self.objective}",
            allowed_substrings=["already enabled", "Nothing changed"],
        )
        interface.runCommand(
            'tellraw @a [{"text":"[animate] In-game controls: "},'
            f'{{"text":"/trigger {self.objective} set 1 clear, "}},'
            f'{{"text":"/trigger {self.objective} set 2 rebuild, "}},'
            f'{{"text":"/trigger {self.objective} set 3 modify"}}]',
            host=self.host,
        )
        self._setup_done = True

    def _run_command_allowing_expected_errors(
        self,
        command: str,
        allowed_substrings: list[str],
    ) -> None:
        result = interface.runCommand(command, host=self.host)
        if not result:
            return
        success, message = result[0]
        if success:
            return
        if any(part in str(message) for part in allowed_substrings):
            return
        print(f"[control] Command failed: {message}")

    def _read_score(self) -> int:
        result = interface.runCommand(
            f"scoreboard players get @p {self.objective}",
            host=self.host,
        )
        if not result:
            return 0
        success, message = result[0]
        if not success:
            return 0
        text = str(message)
        parts = text.split(" has ")
        if len(parts) < 2:
            return 0
        value_text = parts[1].split(" ")[0]
        try:
            return int(value_text)
        except ValueError:
            return 0

    def _reset_score(self) -> None:
        interface.runCommand(
            f"scoreboard players set @a {self.objective} 0",
            host=self.host,
        )
        interface.runCommand(
            f"scoreboard players enable @a {self.objective}",
            host=self.host,
        )

    def poll(self) -> LifecycleAction | None:
        score = self._read_score()
        if score == 0:
            return None
        self._reset_score()
        if score == 1:
            print("[control] Clear requested from in-game trigger.")
            return LifecycleAction("clear")
        if score == 2:
            print("[control] Rebuild requested from in-game trigger.")
            return LifecycleAction("rebuild")
        if score == 3:
            print("[control] Modify requested from in-game trigger.")
            return LifecycleAction("modify")
        print(f"[control] Ignoring unknown trigger value: {score}")
        return None

    def wait_for_action(self, poll_interval_s: float = 0.25) -> LifecycleAction:
        while True:
            action = self.poll()
            if action is not None:
                return action
            time.sleep(poll_interval_s)
