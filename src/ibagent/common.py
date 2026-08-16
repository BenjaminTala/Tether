"""Shared literals used by config, schemas and the engine."""
from typing import Literal

Sleeve = Literal["core", "trend", "spec"]
ActiveSleeve = Literal["trend", "spec"]
RunType = Literal["weekly", "daily", "event"]
Side = Literal["BUY", "SELL"]
