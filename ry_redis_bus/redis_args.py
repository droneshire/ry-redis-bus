import argparse


def add_redis_args(parser: argparse.ArgumentParser) -> None:
    redis_parser = parser.add_argument_group("redis-options")
    redis_parser.add_argument("--redis-host", type=str, default="localhost")
    redis_parser.add_argument("--redis-port", type=int, default=6379)
    redis_parser.add_argument("--redis-db", choices=list(range(16)), default=0)
    redis_parser.add_argument(
        "--redis-db-name",
        type=str,
        default="redis_ipc",
    )

    redis_parser.add_argument("--redis-user", type=str, default="")
    redis_parser.add_argument("--redis-password", type=str, default="")
