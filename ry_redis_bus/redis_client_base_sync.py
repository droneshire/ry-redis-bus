import time
import typing as T

import redis
from ryutils import log
from ryutils.path_util import get_backtrace_file_name
from ryutils.verbose import Verbose

from ry_redis_bus.channels import Channel
from ry_redis_bus.helpers import (
    DEFAULT_COOLDOWN_TIMEOUT,
    DEFAULT_MESSAGE_BACKTRACE_FRAME,
    ITERATION_SLEEP_TIME,
    MAX_COOLDOWN_TIMEOUT,
    NO_SUBSCRIBE_IF_NO_CALLBACK,
    SUBSCRIBE_BACKTRACE_FRAME,
    TIME_BETWEEN_RE_SUBSCRIBE,
    RedisInfo,
    RedisMessageCallback,
    get_redis_connection,
)


class SyncRedisClientBase:
    MESSAGE_WAIT_TIMEOUT = 0  # 0 means no blocking, which we need to support multiple clients
    MAX_PROCESS_MESSAGES_PER_ITERATION = 10000

    def __init__(
        self,
        redis_info: RedisInfo,
        verbose: Verbose,
        default_message_callback: RedisMessageCallback = None,
    ):
        self._client: T.Optional[redis.Redis] = None
        self._pubsub: T.Optional[redis.client.PubSub] = None
        self.redis_info: RedisInfo = redis_info
        self.verbose: Verbose = verbose

        self.stop_listen = False
        self.cooldown = 0.1
        self.time_since_last_message = time.time()
        self.cooldown_start = time.time()

        self.channel_map: T.Dict[str, RedisMessageCallback] = {}
        self.default_message_callback: RedisMessageCallback = default_message_callback

        if self.default_message_callback and callable(self.default_message_callback):
            calling_file = get_backtrace_file_name(frame=DEFAULT_MESSAGE_BACKTRACE_FRAME)
            log.print_warn(
                f"{self.__class__.__name__} Default message callback is set for {calling_file}."
            )

    @property
    def client(self) -> redis.Redis:
        """Returns the Redis client, retrying to connect if necessary."""
        self._client = get_redis_connection(
            redis_client=self._client, redis_info=self.redis_info, retry_counts=5, retry_delay=5
        )
        return self._client

    @property
    def pubsub(self) -> redis.client.PubSub:
        """Returns the Redis pubsub client"""
        if not hasattr(self, "_pubsub") or self._pubsub is None:
            self._pubsub = self.client.pubsub()  # type: ignore
        return T.cast(redis.client.PubSub, self._pubsub)

    def zadd(self, data: T.Any) -> None:
        """Adds the data to the Redis database"""
        self.client.zadd(self.redis_info.db_name, data)

    def subscribe_all(self) -> None:
        log.print_bright("Subscribing to all channels...")
        self.pubsub.psubscribe("*")  # type: ignore

    def subscribe(self, channel: Channel, callback: RedisMessageCallback = None) -> None:
        self._subscribe(str(channel), callback)

    def _subscribe(self, channel: str, callback: RedisMessageCallback = None) -> None:
        calling_file = get_backtrace_file_name(frame=SUBSCRIBE_BACKTRACE_FRAME)

        if self.redis_info == RedisInfo.null():
            log.print_fail(
                f"Redis info is null for {calling_file}. Cannot subscribe to Redis server."
            )
            return

        if NO_SUBSCRIBE_IF_NO_CALLBACK and not callback:
            log.print_fail("Cannot subscribe to a channel without a callback.")
            return

        registered_callback: RedisMessageCallback = callback or (lambda x: None)
        channel_str = str(channel)

        sub_string = "resubscribing" if channel_str in self.channel_map else "subscribed"

        self.channel_map[channel_str] = registered_callback
        self.pubsub.subscribe(channel_str)  # type: ignore

        log.print_bright(
            f"{calling_file} {sub_string} to '{channel}' channel. Waiting for messages..."
        )

    def unsubscribe(self, channel: Channel, delete_map: bool = True) -> None:
        self._unsubscribe(str(channel), delete_map)

    def _unsubscribe(self, channel: str, delete_map: bool = True) -> None:
        if self.redis_info == RedisInfo.null():
            log.print_fail("Redis info is null. Cannot unsubscribe to Redis server.")
            return
        channel_str = str(channel)

        if channel_str in self.channel_map and delete_map:
            del self.channel_map[channel_str]
        self.pubsub.unsubscribe(channel_str)  # type: ignore
        log.print_bright(f"Unsubscribed from '{channel}' channel.")

    def publish(self, channel: Channel, message: T.Union[str, bytes]) -> None:
        self._publish(str(channel), message)

    def _publish(self, channel: str, message: T.Union[str, bytes]) -> None:
        """Publishes the message to the Redis server with timestamp."""
        if self.redis_info == RedisInfo.null():
            log.print_fail("Redis info is null. Cannot publish to Redis server.")
            return

        if self.verbose.ipc:
            log.print_normal(f"Sending message: {message!r} to channel: {channel}...")

        try:
            self.client.publish(str(channel), message)
        except redis.exceptions.ConnectionError as exc:
            log.print_fail(f"Failed to connect to Redis server: {exc}")
            log.print_fail_arrow("Is the server running?")

    def stop(self) -> None:
        self.stop_listen = True
        channels = list(self.channel_map.keys())
        for channel in channels:
            self._unsubscribe(channel, delete_map=False)
        if self._pubsub is not None:
            self.pubsub.close()
            self._pubsub = None

    def close(self) -> None:
        """Close all connections and clean up resources"""
        self.stop()
        if self._client is not None:
            self._client.close()
            self._client = None

    def start(self) -> None:
        self.stop_listen = False
        channels = list(self.channel_map.keys())
        for channel in channels:
            self._subscribe(channel, self.channel_map[channel])

    def step(self) -> None:
        """Steps the redis server"""
        if self.stop_listen:
            return

        now = time.time()

        if self.redis_info == RedisInfo.null():
            return

        if now - self.cooldown_start < self.cooldown:
            return

        processed_messages = 0
        while self._process_redis_message(now):
            processed_messages += 1
            if processed_messages > self.MAX_PROCESS_MESSAGES_PER_ITERATION:
                break

        if now - self.time_since_last_message > TIME_BETWEEN_RE_SUBSCRIBE:
            log.print_bright("Resubscribing to the redis channel...")
            self.stop()
            self.start()
            self.time_since_last_message = now

    def _call_handler(self, handler: RedisMessageCallback, channel: str, item: T.Any) -> None:
        if callable(handler):
            handler(item)
        else:
            log.print_fail(f"Handler for channel {channel} is not callable.")

    def _process_redis_message(self, now: float) -> bool:
        item = {}

        try:
            item = self.pubsub.get_message(timeout=self.MESSAGE_WAIT_TIMEOUT)
            self.cooldown = DEFAULT_COOLDOWN_TIMEOUT
            self.cooldown_start = 0.0
        except KeyboardInterrupt as exc:
            raise KeyboardInterrupt from exc
        except (redis.exceptions.ConnectionError, ValueError) as exc:
            self.cooldown = min(MAX_COOLDOWN_TIMEOUT, self.cooldown * 2.0)
            self.cooldown_start = now
            log.print_fail(f"Redis connection error: {exc}")
            log.print_fail_arrow(f"Attempting to reconnect in {self.cooldown} seconds...")
            # Force reconnection by resetting the pubsub client
            self._pubsub = None
            return False
        except Exception as exc:  # pylint: disable=broad-exception-caught
            self.cooldown = min(MAX_COOLDOWN_TIMEOUT, self.cooldown * 2.0)
            self.cooldown_start = now
            log.print_fail(f"Unexpected error while processing Redis message: {exc}")
            log.print_fail_arrow(f"Sleeping for {self.cooldown} seconds...")
            return False

        if item and item.get("type", "") in ["message", "pmessage"]:
            channel = item.get("channel", "UNKNOWN").decode()

            handler = self.channel_map.get(channel)
            if handler:
                self._call_handler(handler, channel, item)
            elif self.default_message_callback and callable(self.default_message_callback):
                self._call_handler(self.default_message_callback, channel, item)
            else:
                log.print_fail(f"Received message from unknown channel: {channel}")
            self.time_since_last_message = now

        return item is not None

    def run(self) -> None:
        """Runs the redis server"""
        while True:
            if self.stop_listen:
                break
            self.step()
            time.sleep(ITERATION_SLEEP_TIME)
