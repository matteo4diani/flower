# Copyright 2023 Adap GmbH. All Rights Reserved.
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
# ==============================================================================
"""Flower telemetry."""

import datetime
import json
import logging
import os
import platform
import urllib.request
from concurrent.futures import Future, ThreadPoolExecutor
from enum import Enum, auto
from typing import Any, Dict, List, Optional, Union, cast

from flwr.common.version import package_name, package_version

FLWR_TELEMETRY_ENABLED = os.getenv("FLWR_TELEMETRY_ENABLED", "1")
FLWR_TELEMETRY_LOGGING = os.getenv("FLWR_TELEMETRY_LOGGING", "0")

TELEMETRY_EVENTS_URL = "https://telemetry.flower.dev/api/v1/event"

LOGGER_NAME = "flwr-telemetry"
LOGGER_LEVEL = logging.DEBUG


def _configure_logger(log_level: int) -> None:
    console_handler = logging.StreamHandler()
    console_handler.setLevel(log_level)
    console_handler.setFormatter(
        logging.Formatter(
            "%(levelname)s %(name)s %(asctime)s | %(filename)s:%(lineno)d | %(message)s"
        )
    )

    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(log_level)
    logger.addHandler(console_handler)


_configure_logger(LOGGER_LEVEL)


def log(msg: Union[str, Exception]) -> None:
    """Log message using logger at DEBUG level."""
    logging.getLogger(LOGGER_NAME).log(LOGGER_LEVEL, msg)


# Using str as first base type to make it JSON serializable as
# otherwise the following exception will be thrown when serializing
# the event dict:
# TypeError: Object of type EventType is not JSON serializable
class EventType(str, Enum):
    """Types of telemetry events."""

    # This method combined with auto() will set the property value to
    # the property name e.g.
    # `START_CLIENT = auto()` becomes `START_CLIENT = "START_CLIENT"`
    # The type signature is not compatible with mypy, pylint and flake8
    # so each of those needs to be disabled for this line.
    # pylint: disable-next=no-self-argument,arguments-differ,line-too-long
    def _generate_next_value_(name: str, start: int, count: int, last_values: List[Any]) -> Any:  # type: ignore # noqa: E501
        return name

    # Ping
    PING = auto()

    # Client
    START_CLIENT_ENTER = auto()
    START_CLIENT_LEAVE = auto()

    # Server
    START_SERVER_ENTER = auto()
    START_SERVER_LEAVE = auto()

    # New Server
    RUN_SERVER_ENTER = auto()
    RUN_SERVER_LEAVE = auto()

    # Simulation
    START_SIMULATION_ENTER = auto()
    START_SIMULATION_LEAVE = auto()


# Use the ThreadPoolExecutor with max_workers=1 to have a queue
# and also ensure that telemetry calls are not blocking.
state: Dict[str, Optional[ThreadPoolExecutor]] = {
    # Will be assigned ThreadPoolExecutor(max_workers=1)
    # in event() the first time it's required
    "executor": None
}

# In Python 3.7 pylint will throw an error stating that
# "Value 'Future' is unsubscriptable".
# This pylint disable line can be remove when dropping support
# for Python 3.7
# pylint: disable-next=unsubscriptable-object
def event(event_type: EventType) -> Future:  # type: ignore
    """Submit create_event to ThreadPoolExecutor to avoid blocking."""
    if state["executor"] is None:
        state["executor"] = ThreadPoolExecutor(max_workers=1)

    executor: ThreadPoolExecutor = cast(ThreadPoolExecutor, state["executor"])

    result = executor.submit(create_event, event_type)
    return result


def create_event(event_type: EventType) -> str:
    """Create telemetry event."""
    date = datetime.datetime.now(tz=datetime.timezone.utc).isoformat()
    context = {
        "date": date,
        "flower": {
            "package_name": package_name,
            "package_version": package_version,
        },
        "hw": {
            "cpu_count": os.cpu_count(),
        },
        "platform": {
            "system": platform.system(),
            "release": platform.release(),
            "platform": platform.platform(),
            "python_implementation": platform.python_implementation(),
            "python_version": platform.python_version(),
            "machine": platform.machine(),
            "architecture": platform.architecture(),
            "version": platform.uname().version,
        },
    }
    payload = {
        "event_type": event_type,
        "context": context,
    }
    payload_json = json.dumps(payload)
    if FLWR_TELEMETRY_LOGGING == "1":
        log(" - ".join([date, "POST", payload_json]))

    # If telemetry is not disabled with setting FLWR_TELEMETRY_ENABLED=0
    # create a request and send it to the telemetry backend
    if FLWR_TELEMETRY_ENABLED == "1":
        request = urllib.request.Request(
            url=TELEMETRY_EVENTS_URL,
            data=payload_json.encode("utf-8"),
            headers={
                "User-Agent": f"{package_name}/{package_version}",
                "Content-Type": "application/json",
            },
            method="POST",
        )
        try:
            with urllib.request.urlopen(request, timeout=60) as response:
                result = response.read()

            response_json: str = result.decode("utf-8")

            return response_json
        except urllib.error.URLError as ex:
            if FLWR_TELEMETRY_LOGGING == "1":
                log(ex)

    return "disabled"
