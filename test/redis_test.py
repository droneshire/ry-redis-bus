import json
import threading
from test.redis_test_base import RedisOnlyTestBase

import redis
from google.protobuf.message import Message
from google.protobuf.timestamp_pb2 import Timestamp  # pylint: disable=no-name-in-module
from ryutils.verbose import Verbose

from ry_redis_bus.channels import Channel
from ry_redis_bus.helpers import (
    MAX_PUBLISH_LATENCY_TIME,
    RedisInfo,
    deserialize_checks,
    deserialize_message,
)
from ry_redis_bus.redis_client_base import RedisClientBase


class MockProtobufMessage:
    """Mock protobuf message for testing that has the required utime field"""

    def __init__(self) -> None:
        self.utime = Timestamp()
        self.utime.GetCurrentTime()

    def SerializeToString(self) -> bytes:  # pylint: disable=invalid-name
        # Return a simple serialized representation for testing
        # Use a format that can be easily parsed back
        return f"mock_message_{self.utime.seconds}_{self.utime.nanos}".encode()

    def ParseFromString(self, serialized: bytes) -> int:  # pylint: disable=invalid-name
        # Mock parsing - decode the data and extract timestamp components
        try:
            decoded = serialized.decode()
            if decoded.startswith("mock_message_"):
                parts = decoded.split("_")
                if len(parts) >= 4:
                    self.utime.seconds = int(parts[2])
                    self.utime.nanos = int(parts[3])
        except (ValueError, IndexError, AttributeError):
            # If parsing fails, just set default values
            self.utime.seconds = 0
            self.utime.nanos = 0
        return len(serialized)  # Return the number of bytes consumed


class RedisClientTest(RedisOnlyTestBase):
    DEFAULT_CHANNEL = Channel("test_channel", Message)
    DB = 0

    def setUp(self) -> None:
        # Get Redis connection parameters from the container
        conn_params = self.get_redis_connection_params()
        host = conn_params["host"]
        port = conn_params["port"]

        self.redis_client = RedisClientBase(
            RedisInfo(
                host=host,
                port=port,
                db=self.DB,
                user="",
                password="",
                db_name="test_db",
            ),
            verbose=Verbose(verbose_types=["ipc"]),
        )
        self.redis_client.subscribe(self.DEFAULT_CHANNEL, lambda _: None)
        self.redis_simple = redis.Redis(host=host, port=port, db=self.DB)
        self.channel = self.DEFAULT_CHANNEL
        self.message = "test_message"

        self.simple_pubsub = self.redis_simple.pubsub()  # type: ignore
        self.simple_pubsub.subscribe(str(self.channel))

    def tearDown(self) -> None:
        self.redis_client.client.flushdb()

    def test_pubsub(self) -> None:
        message = "test_message"
        did_succeed = False
        result_event = threading.Event()

        def subscriber_thread() -> None:
            nonlocal did_succeed
            for item in self.simple_pubsub.listen():
                if item["type"] == "message":
                    received_message = item["data"].decode()
                    try:
                        self.assertEqual(received_message, message)
                        did_succeed = True
                    finally:
                        result_event.set()
                    return

        subscriber = threading.Thread(target=subscriber_thread)
        subscriber.start()

        self.redis_client.publish(channel=self.channel, message=message)

        result_event.wait()

        if not did_succeed:
            self.fail("Test failed!")

        subscriber.join()

    def test_serialization(self) -> None:
        message = {"foo": "bar"}
        did_succeed = False
        result_event = threading.Event()

        def subscriber_thread() -> None:
            nonlocal did_succeed
            for item in self.simple_pubsub.listen():
                if item["type"] == "message":
                    received_message = item["data"].decode()
                    message_json = json.loads(received_message)
                    try:
                        self.assertEqual(message_json, message)
                        did_succeed = True
                    finally:
                        result_event.set()
                    return

        subscriber = threading.Thread(target=subscriber_thread)
        subscriber.start()

        self.redis_client.publish(channel=self.channel, message=json.dumps(message))

        result_event.wait(1)

        if not did_succeed:
            self.fail("Test failed!")

        subscriber.join()

    def test_pbtypes(self) -> None:
        # Create a mock protobuf message with required fields
        message_pb = MockProtobufMessage()

        did_succeed = False
        result_event = threading.Event()

        def subscriber_thread() -> None:
            nonlocal did_succeed
            for item in self.simple_pubsub.listen():
                if item["type"] == "message":
                    # Create a mock message item that matches what deserialize_message expects
                    mock_item = {"data": item["data"]}
                    # Use the mock message class for deserialization
                    message = deserialize_message(
                        mock_item, MockProtobufMessage, verbose=False  # type: ignore[arg-type]
                    )
                    try:
                        # Check that we got a valid protobuf message
                        self.assertIsNotNone(message)
                        self.assertIsInstance(message, MockProtobufMessage)
                        # Check that it has the required utime field
                        self.assertTrue(hasattr(message, "utime"))
                        did_succeed = True
                    finally:
                        result_event.set()
                    return

        subscriber = threading.Thread(target=subscriber_thread)
        subscriber.start()

        self.redis_client.publish(channel=self.channel, message=message_pb.SerializeToString())

        result_event.wait(1)

        if not did_succeed:
            self.fail("Test failed!")

        subscriber.join()

    def test_deserialize_checks(self) -> None:
        test_message = MockProtobufMessage()

        check_pass = deserialize_checks(
            channel="test_channel", message_pb=test_message  # type: ignore[arg-type]
        )
        self.assertTrue(check_pass)

        # Test with expired timestamp
        incrment_time = MAX_PUBLISH_LATENCY_TIME + 1
        incrment_time *= -1.0
        self._increment_timestamp(incrment_time, test_message.utime)

        check_pass = deserialize_checks(
            channel="test_channel", message_pb=test_message  # type: ignore[arg-type]
        )
        self.assertFalse(check_pass)

    def _increment_timestamp(self, increment_seconds: float, timestamp: Timestamp) -> None:
        """Helper method to increment a timestamp by the given number of seconds"""
        current_seconds = timestamp.seconds + timestamp.nanos / 1_000_000_000
        new_seconds = current_seconds + increment_seconds

        # Convert back to seconds and nanoseconds
        timestamp.seconds = int(new_seconds)
        timestamp.nanos = int((new_seconds - timestamp.seconds) * 1_000_000_000)
