import argparse
import os

CONFIG_REDIS_HOST = os.getenv("REDIS_HOST", "localhost")
CONFIG_REDIS_PORT = int(os.getenv("REDIS_PORT", "6379"))
CONFIG_REDIS_DB = int(os.getenv("REDIS_DB", "0"))
CONFIG_REDIS_DB_NAME = os.getenv("REDIS_DB_NAME", "redis_ipc")
CONFIG_REDIS_USER = os.getenv("REDIS_USER", "")
CONFIG_REDIS_PASSWORD = os.getenv("REDIS_PASSWORD", "")


def add_redis_args(parser: argparse.ArgumentParser) -> None:
    redis_parser = parser.add_argument_group("redis-options")
    redis_parser.add_argument("--redis-host", type=str, default=CONFIG_REDIS_HOST)
    redis_parser.add_argument("--redis-port", type=int, default=CONFIG_REDIS_PORT)
    redis_parser.add_argument("--redis-db", choices=list(range(16)), default=CONFIG_REDIS_DB)
    redis_parser.add_argument(
        "--redis-db-name",
        type=str,
        default=CONFIG_REDIS_DB_NAME,
    )

    redis_parser.add_argument("--redis-user", type=str, default=CONFIG_REDIS_USER)
    redis_parser.add_argument("--redis-password", type=str, default=CONFIG_REDIS_PASSWORD)
