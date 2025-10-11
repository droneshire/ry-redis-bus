"""
Base test class that provides containerized Redis for testing.

This module provides a base class for tests that require Redis.
It uses testcontainers to automatically spin up and tear down Docker containers
for testing, eliminating the need for manually running database servers.
"""

import os
import unittest
from typing import Optional

from testcontainers.redis import RedisContainer


class RedisOnlyTestBase(unittest.TestCase):
    """Base test class that provides only Redis container."""

    redis_container: Optional[RedisContainer] = None
    _containers_started = False

    @classmethod
    def setUpClass(cls) -> None:
        """Set up Redis container once for all tests in the class."""
        super().setUpClass()

        # Start Redis container
        cls.redis_container = RedisContainer("redis:latest")
        cls.redis_container.start()

        # Set environment variables for Redis
        os.environ["REDIS_HOST"] = cls.redis_container.get_container_host_ip()
        os.environ["REDIS_PORT"] = str(cls.redis_container.get_exposed_port(6379))

        cls._containers_started = True

    @classmethod
    def tearDownClass(cls) -> None:
        """Tear down Redis container after all tests in the class."""
        if cls.redis_container:
            cls.redis_container.stop()

        cls._containers_started = False
        super().tearDownClass()

    @classmethod
    def get_redis_connection_params(cls) -> dict:
        """Get Redis connection parameters.

        Returns:
            dict: Connection parameters for Redis
        """
        if not cls._containers_started or not cls.redis_container:
            raise RuntimeError("Container not started. Call setUpClass first.")

        return {
            "host": cls.redis_container.get_container_host_ip(),
            "port": cls.redis_container.get_exposed_port(6379),
        }
