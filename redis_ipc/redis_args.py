import argparse

from config import constants


def add_redis_args(parser: argparse.ArgumentParser) -> None:
    redis_parser = parser.add_argument_group("redis-options")
    redis_parser.add_argument("--redis-host", type=str, default=constants.REDIS_HOST)
    redis_parser.add_argument("--redis-port", type=int, default=constants.REDIS_PORT)
    redis_parser.add_argument("--redis-db", choices=list(range(16)), default=constants.REDIS_DB_NUM)
    redis_parser.add_argument(
        "--redis-db-name",
        type=str,
        default=constants.REDIS_DB_NAME,
    )

    redis_parser.add_argument("--redis-user", type=str, default=constants.REDIS_USER)
    redis_parser.add_argument("--redis-password", type=str, default=constants.REDIS_PASSWORD)
