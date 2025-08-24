import json
import threading
import unittest

import redis
from google.protobuf.message import Message
from google.protobuf.timestamp_pb2 import Timestamp  # pylint: disable=no-name-in-module
from ryutils.verbose import Verbose

from redis_ipc.channels import Channel
from redis_ipc.helpers import MAX_PUBLISH_LATENCY_TIME, RedisInfo, deserialize_checks, deserialize_message
from redis_ipc.redis_client_base import RedisClientBase
from pb_types.example_pb2 import ExampleEnumPb  # pylint: disable=no-name-in-module
from pb_types.example_pb2 import ExampleMessagePb  # pylint: disable=no-name-in-module
from utils.pb_helper import increment_timestamp


class RedisClientTest(unittest.TestCase):
    DEFAULT_CHANNEL = Channel("test_channel", Message)
    PORT = 6379
    DB = 0
    HOST = "localhost"

    def setUp(self) -> None:
        self.redis_client = RedisClientBase(
            RedisInfo(
                host=self.HOST,
                port=self.PORT,
                db=self.DB,
                user="",
                password="",
                db_name="test_db",
            ),
            verbose=Verbose(),
        )
        self.redis_client.subscribe(self.DEFAULT_CHANNEL, lambda _: None)
        self.redis_simple = redis.Redis(host=self.HOST, port=self.PORT, db=self.DB)
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
        message_pb = ExampleMessagePb()
        message_pb.example_enum = ExampleEnumPb.KNOWN
        timestamp = Timestamp()
        timestamp.GetCurrentTime()
        message_pb.utime.CopyFrom(timestamp)
        message_pb.mtime.CopyFrom(timestamp)

        did_succeed = False
        result_event = threading.Event()

        def subscriber_thread() -> None:
            nonlocal did_succeed
            for item in self.simple_pubsub.listen():
                if item["type"] == "message":
                    message = deserialize_message(item, ExampleMessagePb, verbose=False)
                    try:
                        self.assertEqual(message_pb, message)
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
        test_message = ExampleMessagePb()
        timestamp = Timestamp()
        timestamp.GetCurrentTime()
        test_message.utime.CopyFrom(timestamp)

        check_pass = deserialize_checks(channel="test_channel", message_pb=test_message)
        self.assertTrue(check_pass)

        incrment_time = MAX_PUBLISH_LATENCY_TIME + 1
        incrment_time *= -1.0
        increment_timestamp(incrment_time, test_message.utime)

        check_pass = deserialize_checks(channel="test_channel", message_pb=test_message)
        self.assertFalse(check_pass)
