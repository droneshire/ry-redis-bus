from google.protobuf.message import Message
from ryutils.verbose import Verbose

from ry_redis_bus.channels import Channel
from ry_redis_bus.helpers import RedisInfo, message_handler
from ry_redis_bus.redis_client_base import RedisClientBase


class RedisReceiver(RedisClientBase):
    """Simple class that subscribes to a redis server and stores messages in a database"""

    def __init__(
        self,
        redis_info: RedisInfo,
        channel: Channel,
        verbose: Verbose,
    ):
        super().__init__(
            redis_info,
            verbose=verbose,
        )
        self.subscribe(channel, self.process_message)

    @message_handler
    def process_message(self, message_pb: Message) -> None:
        print(f"Received message: {message_pb}")
