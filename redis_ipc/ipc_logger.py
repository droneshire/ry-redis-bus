"""
Helper class that logs IPC messages to the
database.

It subscribes to all redis IPC messages and logs them.
"""

import argparse
import typing as T

from google.protobuf.timestamp_pb2 import Timestamp  # pylint: disable=no-name-in-module
from ryutils import log
from ryutils.verbose import Verbose

from database.dynamic_table import DynamicTableDb
from ipc.redis_client_base import RedisClientBase, RedisInfo
from pb_types.logging_pb2 import LogIpcMessagePb  # pylint: disable=no-name-in-module


class IpcLogger(RedisClientBase):
    LOGGER_DB_TABLE = "LogIpcMessage"

    def __init__(self, verbose: Verbose, args: argparse.Namespace) -> None:
        redis_info: RedisInfo = RedisInfo(
            host=args.redis_host,
            port=args.redis_port,
            db=args.redis_db,
            user=args.redis_user,
            password=args.redis_password,
            db_name=args.redis_db_name,
        )
        super().__init__(
            redis_info=redis_info, verbose=verbose, default_message_callback=self.log_message
        )

        self.db_name = args.postgres_db

    def log_message(self, message: T.Any) -> None:
        """Logs the message to the database"""
        if message is None:
            return

        channel = message["channel"].decode("utf-8")

        data = message["data"]
        if self.verbose.logger:
            log.print_normal(f"{channel}: {data}")

        timestamp = Timestamp()
        timestamp.GetCurrentTime()

        log_msg_pb = LogIpcMessagePb()
        log_msg_pb.message = data
        log_msg_pb.channel = channel
        log_msg_pb.utime.CopyFrom(timestamp)

        DynamicTableDb.log_data_to_db(log_msg_pb, self.db_name, self.LOGGER_DB_TABLE)
