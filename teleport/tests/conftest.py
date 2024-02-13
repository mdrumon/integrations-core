# (C) Datadog, Inc. 2024-present
# All rights reserved
# Licensed under a 3-clause BSD style license (see LICENSE)
import os
import pytest

from datadog_checks.dev import docker_run
from datadog_checks.dev import get_here
from datadog_checks.teleport import TeleportCheck

@pytest.fixture(scope='session')
def dd_environment():
    compose_file = os.path.join(get_here(), 'docker', 'docker-compose.yaml')
   
    with docker_run(compose_file):
        instance = {
            "diagnostic_url": "http://127.0.0.1:3000"
        }
        yield instance

@pytest.fixture
def instance():
    return {}