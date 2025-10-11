import typing as T

import redis
import redis.asyncio as aioredis
from ryutils.verbose import Verbose

from ry_redis_bus.channels import Channel
from ry_redis_bus.helpers import RedisInfo, RedisMessageCallback
from ry_redis_bus.redis_client_base_async import AsyncRedisClientBase
from ry_redis_bus.redis_client_base_sync import SyncRedisClientBase


# pylint: disable=too-many-public-methods
class RedisClientBase:
    """
    A class that combines both the async and sync redis clients.
    """

    def __init__(
        self,
        redis_info: RedisInfo,
        verbose: Verbose,
        default_message_callback: RedisMessageCallback = None,
    ):
        self.verbose = verbose
        self.async_client = AsyncRedisClientBase(redis_info, verbose, default_message_callback)
        self.sync_client = SyncRedisClientBase(redis_info, verbose, default_message_callback)

    @property
    async def aclient(self) -> aioredis.Redis:
        """Async Redis client."""
        return await self.async_client.client

    @property
    def client(self) -> redis.Redis:
        """Sync Redis client."""
        return self.sync_client.client

    @property
    async def apubsub(self) -> aioredis.client.PubSub:
        """Async Redis pubsub client."""
        return await self.async_client.pubsub

    @property
    def pubsub(self) -> redis.client.PubSub:
        """Sync Redis pubsub client."""
        return self.sync_client.pubsub

    async def azadd(self, data: T.Any) -> None:
        """Async version of zadd."""
        await self.async_client.zadd(data)

    def zadd(self, data: T.Any) -> None:
        """Sync version of zadd."""
        self.sync_client.zadd(data)

    async def asubscribe_all(self) -> None:
        """Async version of subscribe_all."""
        await self.async_client.subscribe_all()

    def subscribe_all(self) -> None:
        """Sync version of subscribe_all."""
        self.sync_client.subscribe_all()

    async def asubscribe(self, channel: Channel, callback: RedisMessageCallback) -> None:
        """Async version of subscribe."""
        await self.async_client.subscribe(channel, callback)

    def subscribe(self, channel: Channel, callback: RedisMessageCallback) -> None:
        """Sync version of subscribe."""
        self.sync_client.subscribe(channel, callback)

    async def apublish(self, channel: Channel, message: T.Any) -> None:
        """Async version of publish."""
        await self.async_client.publish(channel, message)

    def publish(self, channel: Channel, message: T.Any) -> None:
        """Sync version of publish."""
        self.sync_client.publish(channel, message)

    async def aunsubscribe(self, channel: Channel) -> None:
        """Async version of unsubscribe."""
        await self.async_client.unsubscribe(channel)

    def unsubscribe(self, channel: Channel) -> None:
        """Sync version of unsubscribe."""
        self.sync_client.unsubscribe(channel)

    async def astop(self) -> None:
        """Async version of stop."""
        await self.async_client.stop()

    def stop(self) -> None:
        """Sync version of stop."""
        self.sync_client.stop()

    async def astart(self) -> None:
        """Async version of start."""
        await self.async_client.start()

    def start(self) -> None:
        """Sync version of start."""
        self.sync_client.start()

    async def astep(self) -> None:
        """Async version of step."""
        await self.async_client.step()

    def step(self) -> None:
        """Sync version of step."""
        self.sync_client.step()

    async def arun(self) -> None:
        """Async version of run."""
        await self.async_client.run()

    def run(self) -> None:
        """Sync version of run."""
        self.sync_client.run()

    async def aclose(self) -> None:
        """Async version of close."""
        await self.async_client.close()

    def close(self) -> None:
        """Sync version of close."""
        self.sync_client.close()
