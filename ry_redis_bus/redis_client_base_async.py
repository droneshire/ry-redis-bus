import asyncio
import time
import typing as T

import redis.asyncio as aioredis
import redis.exceptions as redis_exc
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
)


class AsyncRedisClientBase:
    MESSAGE_WAIT_TIMEOUT = 0

    def __init__(
        self,
        redis_info: RedisInfo,
        verbose: Verbose,
        default_message_callback: RedisMessageCallback = None,
    ):
        self._client: T.Optional[aioredis.Redis] = None
        self._pubsub: T.Optional[aioredis.client.PubSub] = None
        self.redis_info: RedisInfo = redis_info
        self.verbose: Verbose = verbose

        self.stop_listen = False
        self.cooldown = 0.1
        self.time_since_last_message = 0.0
        self.cooldown_start = 0.0

        self.channel_map: T.Dict[str, RedisMessageCallback] = {}
        self.default_message_callback: RedisMessageCallback = default_message_callback
        if self.default_message_callback and callable(self.default_message_callback):
            calling_file = get_backtrace_file_name(frame=DEFAULT_MESSAGE_BACKTRACE_FRAME)
            log.print_warn(
                f"{self.__class__.__name__} Default message callback is set for {calling_file}."
            )

    @property
    async def client(self) -> aioredis.Redis:
        """Returns the Redis client, retrying to connect if necessary."""
        if not self._client:
            self._client = await self._get_redis_connection(self.redis_info)
        return self._client

    @property
    async def pubsub(self) -> aioredis.client.PubSub:
        """Returns the Redis pubsub client"""
        if not self._pubsub or self._pubsub is None:
            self._pubsub = (await self.client).pubsub()
        return self._pubsub

    async def zadd(self, data: T.Any) -> None:
        """Adds the data to the Redis database"""
        await (await self.client).zadd(self.redis_info.db_name, data)

    async def _get_redis_connection(
        self, redis_info: RedisInfo, retry_counts: int = 5, retry_delay: int = 5
    ) -> aioredis.Redis:
        """Gets the Redis connection with retry."""
        for _ in range(retry_counts):
            try:
                redis_url = "redis://"
                if redis_info.user and redis_info.password:
                    redis_url = (
                        f"redis://{redis_info.user}:{redis_info.password}@"
                        f"{redis_info.host}:{redis_info.port}/{redis_info.db}"
                    )
                elif redis_info.password:
                    redis_url = (
                        f"redis://:{redis_info.password}@{redis_info.host}:"
                        f"{redis_info.port}/{redis_info.db}"
                    )
                else:
                    redis_url = f"redis://{redis_info.host}:{redis_info.port}/{redis_info.db}"

                client = aioredis.from_url(redis_url)  # type: ignore
                await client.ping()  # Test connection
                return T.cast(aioredis.Redis, client)
            except redis_exc.ConnectionError as exc:
                log.print_fail(f"Failed to connect to Redis server: {exc}")
                log.print_fail_arrow(f"Retrying in {retry_delay} seconds...")
                await asyncio.sleep(retry_delay)
        raise redis_exc.ConnectionError("Failed to connect to Redis server after retries")

    async def subscribe_all(self) -> None:
        """Subscribe to all channels."""
        log.print_bright("Subscribing to all channels...")
        await (await self.pubsub).psubscribe("*")

    async def subscribe(self, channel: Channel, callback: RedisMessageCallback = None) -> None:
        await self._subscribe(str(channel), callback)

    async def _subscribe(self, channel: str, callback: RedisMessageCallback = None) -> None:
        calling_file = get_backtrace_file_name(frame=SUBSCRIBE_BACKTRACE_FRAME)

        if self.redis_info == RedisInfo.null():
            log.print_fail(
                f"Redis info is null for {calling_file}. Cannot subscribe to Redis server."
            )
            return

        if NO_SUBSCRIBE_IF_NO_CALLBACK and not callback:
            log.print_fail("Cannot subscribe to a channel without a callback.")
            return

        registered_callback = callback or (lambda x: None)
        channel_str = str(channel)

        sub_string = "resubscribing" if channel_str in self.channel_map else "subscribed"

        self.channel_map[channel_str] = registered_callback

        await (await self.pubsub).subscribe(channel_str)  # This must be awaited

        log.print_bright(
            f"{calling_file} {sub_string} to '{channel}' channel. Waiting for messages..."
        )

    async def unsubscribe(self, channel: Channel, delete_map: bool = True) -> None:
        await self._unsubscribe(str(channel), delete_map)

    async def _unsubscribe(self, channel: str, delete_map: bool = True) -> None:
        if self.redis_info == RedisInfo.null():
            log.print_fail("Redis info is null. Cannot unsubscribe to Redis server.")
            return
        channel_str = str(channel)

        if channel_str in self.channel_map and delete_map:
            del self.channel_map[channel_str]
        await (await self.pubsub).unsubscribe(channel_str)
        log.print_bright(f"Unsubscribed from '{channel}' channel.")

    async def publish(self, channel: Channel, message: T.Union[str, bytes]) -> None:
        """Publishes message to channel without blocking using create_task."""
        await self._publish(str(channel), message)

    async def _publish(self, channel: str, message: T.Union[str, bytes]) -> None:
        """Publishes the message to the Redis server with timestamp."""
        if self.redis_info == RedisInfo.null():
            log.print_fail("Redis info is null. Cannot publish to Redis server.")
            return

        if self.verbose.ipc:
            log.print_normal(f"Sending message: {message!r} to channel: {channel}...")

        try:
            client = await self.client
            await client.publish(channel, message)
        except redis_exc.RedisError as exc:
            log.print_fail(f"Failed to connect to Redis server: {exc}")
            log.print_fail_arrow("Is the server running?")

    async def stop(self) -> None:
        self.stop_listen = True
        channels = list(self.channel_map.keys())
        for channel in channels:
            await self._unsubscribe(channel, delete_map=False)
        if self._pubsub is not None:
            await (await self.pubsub).close()
            self._pubsub = None

    async def close(self) -> None:
        """Close all connections and clean up resources"""
        await self.stop()
        if self._client is not None:
            await self._client.close()
            self._client = None

    async def start(self) -> None:
        self.stop_listen = False
        channels = list(self.channel_map.keys())
        for channel in channels:
            await self._subscribe(channel, self.channel_map[channel])

    async def step(self) -> None:
        """Steps the redis server"""
        if self.stop_listen:
            return

        now = time.time()

        if now - self.cooldown_start < self.cooldown:
            return

        if self.redis_info == RedisInfo.null():
            return

        while await self._process_redis_message(now):
            pass

        if now - self.time_since_last_message > TIME_BETWEEN_RE_SUBSCRIBE:
            log.print_bright("Resubscribing to the redis channel...")
            await self.stop()
            await self.start()
            self.time_since_last_message = now

    async def _call_handler(self, handler: RedisMessageCallback, channel: str, item: T.Any) -> None:
        if callable(handler):
            if asyncio.iscoroutinefunction(handler):
                # Await if it's a coroutine
                await handler(item)
            else:
                # Call normally if it's not a coroutine
                handler(item)
        else:
            log.print_fail(f"Handler for channel {channel} is not callable.")

    async def _process_redis_message(self, now: float) -> bool:
        try:
            item = await (await self.pubsub).get_message(timeout=self.MESSAGE_WAIT_TIMEOUT)
            if item and item.get("type", "") in ["message", "pmessage"]:
                asyncio.create_task(self._handle_message(item))
                self.time_since_last_message = now
            self.cooldown = DEFAULT_COOLDOWN_TIMEOUT
            self.cooldown_start = 0.0
            return item is not None
        except redis_exc.ConnectionError as exc:
            self.cooldown = min(MAX_COOLDOWN_TIMEOUT, self.cooldown * 2.0)
            self.cooldown_start = now
            log.print_fail(f"Failed to connect to Redis server: {exc}")
            log.print_fail_arrow(f"Is the server running? Sleeping for {self.cooldown}...")
            return False

    async def _handle_message(self, item: T.Any) -> None:
        channel = item.get("channel", "UNKNOWN").decode()

        # Check if the handler is a coroutine and await it if so
        handler = self.channel_map.get(channel)
        if handler:
            await self._call_handler(handler, channel, item)
        elif self.default_message_callback and callable(self.default_message_callback):
            await self._call_handler(self.default_message_callback, channel, item)
        else:
            log.print_fail(f"Received message from unknown channel: {channel}")

    async def run(self) -> None:
        """Runs the redis server asynchronously"""
        while not self.stop_listen:
            await self.step()
            await asyncio.sleep(ITERATION_SLEEP_TIME)  # Yield control to the event loop
