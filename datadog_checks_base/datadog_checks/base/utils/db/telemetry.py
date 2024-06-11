# (C) Datadog, Inc. 2024-present
# All rights reserved
# Licensed under a 3-clause BSD style license (see LICENSE)
import json
import logging
from time import time
from typing import Callable, Dict, NamedTuple, Optional
from .utils import default_json_event_encoding
from datadog_checks.base.utils.common import to_native_string
from datadog_checks.base.agent import datadog_agent


logger = logging.getLogger(__name__)

FLUSH_INTERVAL = 60

class TelemetryOperation(NamedTuple):
    integration: str
    operation: str
    elapsed: Optional[float]
    count: Optional[int]

class Telemetry:
    """
    This class supports telemetry collection for database integrations. Telemetry is sent to the instance, then emitted
    to the dbm-metrics event track on an interval. Duplicate operations are deduped to last submitted before an event
    submission.
    """

    _buffer: Dict[str, TelemetryOperation]

    def __init__(self, log):
        self._buffer = {}
        self._log = log
        self._log.warn("aq: CREATED TELEMETRY")

    def add(self, integration:str, operation:str, elapsed: Optional[float], count: Optional[int]):
        """
        Add a telemetry event for a given integration and operation. Events can have a count and/or an elapsed time.

        :param integration (_str_): Name of the calling integration. Examples: postgres, mysql
        :param operation (_str_): Name of the event operation. Examples: collect_schema, collect_query_metrics
        :param elapsed (_Optional[float]_): Time elapsed for the operation in milliseconds. Example: 20ms to query for list of tables in schema collection
        :param count (_Optional[int]_): Count of relevant resources. Example: 5 tables collected as part of schema collection        
        """
        self._buffer[f'{integration}.{operation}'] = {integration, operation, elapsed, count}
        self._last_flush = 0
    
    def flush(self, submit: Callable[[str], None], force = False):
        """
        Flushes any buffered events. The Telemetry instance tracks the time since last flush and will skip executions less than FLUSH_INTERVAL
        since the last events sent.

        :param submit (_function_): Submission function for the event. Typically this would be self.database_monitoring_query_metrics.
        :param force (_bool_): Send events even if less than FLUSH_INTERVAL has elapsed. Only used for testing.
        """
        elapsed_s = time() - self._last_flush 
        self._log.warn("aq: telemetry flush after $d", elapsed_s)
        if not force and elapsed_s < FLUSH_INTERVAL:
            return
        for op in self._buffer.values():
            event = {
                "ddagentversion": datadog_agent.get_version(),
                "timestamp": time() * 1000,
                "kind": "agent_metrics",
                "integration": op.integration,
                "operation": op.operation,
                "elapsed": op.elapsed,
                "count": op.count,
            }

            json_event = json.dumps(event, default=default_json_event_encoding)
            self._log.warn("aq: Reporting the following payload for telemetry collection: {}".format(json_event))
            submit(json_event)