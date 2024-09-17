﻿# (C) Datadog, Inc. 2021-present
# All rights reserved
# Licensed under a 3-clause BSD style license (see LICENSE)

from __future__ import unicode_literals

import concurrent
import copy
import datetime
import json
import logging
import os
import re
import threading
import time
import xml.etree.ElementTree as ET
from concurrent.futures.thread import ThreadPoolExecutor

import mock
import pytest
from dateutil import parser

from datadog_checks.base.utils.db.utils import DBMAsyncJob, default_json_event_encoding
from datadog_checks.dev.ci import running_on_windows_ci
from datadog_checks.sqlserver import SQLServer
from datadog_checks.sqlserver.activity import DM_EXEC_REQUESTS_COLS, _hash_to_hex

from .common import CHECK_NAME, OPERATION_TIME_METRIC_NAME, SQLSERVER_MAJOR_VERSION
from .utils import create_deadlock

try:
    import pyodbc
except ImportError:
    pyodbc = None


def run_check_and_return_deadlock_payloads(dd_run_check, check, aggregator):
    dd_run_check(check)
    dbm_activity = aggregator.get_event_platform_events("dbm-activity")
    matched = []
    for event in dbm_activity:
        if "sqlserver_deadlocks" in event:
            matched.append(event)
    return matched

@pytest.mark.integration
@pytest.mark.usefixtures('dd_environment')
def test_deadlocks(aggregator, dd_run_check, init_config, dbm_instance):
    dbm_instance['deadlocks_collection'] = {
        'enabled': True,
        'run_sync': True,
        'collection_interval': 0.1,
    }
    dbm_instance['query_activity']['enabled'] = False
    
    sqlserver_check = SQLServer(CHECK_NAME, init_config, [dbm_instance])
    
    deadlock_payloads = run_check_and_return_deadlock_payloads(dd_run_check, sqlserver_check, aggregator)
    assert not deadlock_payloads, "shouldn't have sent an empty payload"
    
    created_deadlock = False
    # Rarely instead of creating a deadlock one of the transactions time outs
    for _ in range(0, 3):
        bob_conn = _get_conn_for_user(dbm_instance, 'bob', 3)
        fred_conn = _get_conn_for_user(dbm_instance, 'fred', 3)
        created_deadlock = create_deadlock(bob_conn, fred_conn)
        bob_conn.close()
        fred_conn.close()
        if created_deadlock:
            break
    try:
        assert created_deadlock, "Couldn't create a deadlock, exiting"
    except AssertionError as e:
        raise e
    
    dbm_instance_no_dbm = copy.deepcopy(dbm_instance)
    dbm_instance_no_dbm['dbm'] = False
    sqlserver_check_no_dbm = SQLServer(CHECK_NAME, init_config, [dbm_instance_no_dbm])
    deadlock_payloads = run_check_and_return_deadlock_payloads(dd_run_check, sqlserver_check_no_dbm, aggregator)
    assert len(deadlock_payloads) == 0, "deadlock should be behind dbm"
    
    dbm_instance['dbm_enabled'] = True
    deadlock_payloads = run_check_and_return_deadlock_payloads(dd_run_check, sqlserver_check, aggregator)
    try:
        assert len(deadlock_payloads) == 1, "Should have collected one deadlock payload, but collected: {}.".format(len(deadlock_payloads))
    except AssertionError as e:
        raise e
    assert isinstance(deadlock_payloads, dict), "Should have collected a dictionary"
    #deadlocks = deadlock_payloads[0]['sqlserver_deadlocks']
    deadlocks = deadlock_payloads['sqlserver_deadlocks']
    found = 0    
    for d in deadlocks:
        assert not "ERROR" in d, "Shouldn't have generated an error"
        try:
            root = ET.fromstring(d)
        except ET.ParseError as e:
            logging.error("deadlock events: %s", str(deadlocks))
            raise e
        process_list = root.find(".//process-list")
        for process in process_list.findall('process'):
            if (
                process.find('inputbuf').text
                == "UPDATE [datadog_test-1].dbo.deadlocks SET b = b + 100 WHERE a = 2;"
            ):
                found += 1
    try:
        assert found == 1, "Should have collected the UPDATE statement in deadlock exactly once, but collected: {}.".format(found)
    except AssertionError as e:
        logging.error("deadlock XML: %s", str(d))
        raise e
