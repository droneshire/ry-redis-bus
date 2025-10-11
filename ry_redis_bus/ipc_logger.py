"""
Helper class that logs IPC messages to the
database.

It subscribes to all redis IPC messages and logs them.
"""

import argparse
import typing as T
from dataclasses import dataclass

from google.protobuf.timestamp_pb2 import Timestamp  # pylint: disable=no-name-in-module
from ryutils import log
from ryutils.verbose import Verbose

from ry_redis_bus.redis_client_base import RedisClientBase, RedisInfo


@dataclass
class LogIpcMessage:
    utime: Timestamp
    message: bytes
    channel: str


class IpcLogger(RedisClientBase):
    def __init__(
        self,
        verbose: Verbose,
        args: argparse.Namespace,
        log_callback: T.Callable[[LogIpcMessage], None],
    ) -> None:
        redis_info: RedisInfo = RedisInfo(
            host=args.redis_host,
            port=args.redis_port,
            db=args.redis_db,
            user=args.redis_user,
            password=args.redis_password,
            db_name=args.redis_db_name,
        )
        super().__init__(
            redis_info=redis_info,
            verbose=verbose,
            default_message_callback=(self.log_message_callback),
        )
        self.log_callback = log_callback

    def log_message_callback(self, message: T.Any) -> None:
        log_msg = self.log_message(message)
        if log_msg is None:
            return
        if self.log_callback is not None:
            self.log_callback(log_msg)

    def log_message(self, message: T.Any) -> T.Optional[LogIpcMessage]:
        """Logs the message to the database"""
        if message is None:
            return None

        channel = message["channel"].decode("utf-8")

        data = message["data"]
        if self.verbose.logger:
            log.print_normal(f"{channel}: {data}")

        timestamp = Timestamp()
        timestamp.GetCurrentTime()

        log_msg = LogIpcMessage(
            utime=timestamp,
            message=data,
            channel=channel,
        )

        return log_msg
