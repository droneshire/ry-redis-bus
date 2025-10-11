import asyncio
import datetime
import functools
import inspect
import time
import typing as T

import redis
from google.protobuf.message import DecodeError, Message
from google.protobuf.timestamp_pb2 import Timestamp  # pylint: disable=no-name-in-module
from ryutils import log
from ryutils.path_util import get_backtrace_file_name

FuncTyping = T.Union[
    T.Callable[..., T.Optional[None]],
    T.Coroutine[T.Any, T.Any, T.Optional[None]],
    T.Callable[..., T.Coroutine[T.Any, T.Any, None]],
]

RedisMessageCallback = T.Union[
    T.Callable[[T.Any], None],
    T.Callable[[T.Any], T.Coroutine[T.Any, T.Any, None]],
    None,
]


DEFAULT_COOLDOWN_TIMEOUT = 0.1
ITERATION_SLEEP_TIME = 0.01
MAX_COOLDOWN_TIMEOUT = 10.0
TIME_BETWEEN_RE_SUBSCRIBE = 60.0 * 60.0 * 12.0
NO_SUBSCRIBE_IF_NO_CALLBACK = True
SUBSCRIBE_BACKTRACE_FRAME = 4
LATENCY_BACKTRACE_FRAME = 7
DEFAULT_MESSAGE_BACKTRACE_FRAME = 3
MAX_PUBLISH_LATENCY_TIME = 2.0


class RedisInfo:
    def __init__(self, host: str, port: int, db: int, user: str, password: str, db_name: str):
        self.host = host
        self.port = port
        self.db = db
        self.user = user
        self.password = password
        self.db_name = db_name

    @classmethod
    def null(cls) -> "RedisInfo":
        return cls("", 0, 0, "", "", "")

    def __eq__(self, other: T.Any) -> bool:
        if not isinstance(other, RedisInfo):
            return False

        return (
            self.host == other.host
            and self.port == other.port
            and self.db == other.db
            and self.user == other.user
            and self.password == other.password
            and self.db_name == other.db_name
        )

    def __repr__(self) -> str:
        values = [
            f"{key}={'*' * min(8, len(value)) if key == 'password' and value else value}"
            for key, value in self.__dict__.items()
        ]
        values_string = "\n\t".join(values)
        return f"RedisInfo(\n\t{values_string}\n)"

    def __str__(self) -> str:
        return self.__repr__()

    def __hash__(self) -> int:
        return hash((self.host, self.port, self.db, self.user, self.password, self.db_name))


def get_redis_client(
    redis_info: RedisInfo,
) -> redis.Redis:
    if redis_info.user and redis_info.password:
        return T.cast(
            redis.Redis,
            redis.Redis(
                host=redis_info.host,
                port=redis_info.port,
                db=redis_info.db,
                username=redis_info.user,
                password=redis_info.password,
            ),
        )

    if redis_info.password:
        return T.cast(
            redis.Redis,
            redis.Redis(
                host=redis_info.host,
                port=redis_info.port,
                db=redis_info.db,
                password=redis_info.password,
            ),
        )

    return T.cast(
        redis.Redis, redis.Redis(host=redis_info.host, port=redis_info.port, db=redis_info.db)
    )


def get_redis_connection(
    redis_info: RedisInfo,
    redis_client: T.Optional[redis.Redis] = None,
    retry_counts: int = 2,
    retry_delay: int = 5,
) -> redis.Redis:
    """Gets the Redis connection with retry"""
    if redis_client is not None:
        try:
            if redis_client.ping():
                return redis_client
        except (redis.exceptions.ConnectionError, redis.exceptions.RedisError):
            # Connection is stale, will retry below
            pass

    if redis_info == RedisInfo.null():
        raise redis.exceptions.ConnectionError("Redis info is null")

    for _ in range(retry_counts):
        try:
            redis_client = get_redis_client(redis_info)
            redis_client.ping()
            return redis_client
        except KeyboardInterrupt as exc:
            raise KeyboardInterrupt from exc
        except redis.exceptions.ConnectionError as exc:
            log.print_fail(f"Failed to connect to Redis server:\n{redis_info}\n{exc}")
            log.print_fail_arrow(f"Retrying in {retry_delay} seconds...")
            time.sleep(retry_delay)

    raise redis.exceptions.ConnectionError("Failed to connect to Redis server")


def deserialize_message(
    message: T.Any, message_class: T.Type[Message], verbose: bool = False
) -> T.Optional[Message]:
    """Deserializes the message from the Redis server"""
    if not isinstance(message, dict) or "data" not in message:
        log.print_fail(f"Invalid message format, expected dict with 'data' key: {message}")
        return None

    data = message["data"]
    try:
        message_pb: Message = message_class()
        message_pb.ParseFromString(data)
    except DecodeError:
        log.print_fail(f"Failed to decode message as {message_class.__name__}: {message}")
        return None

    if verbose:
        log.print_normal(f"Received message: {message_pb}")

    return message_pb


def get_timestamp_pb_from_string(timestamp: str) -> Timestamp:
    mtime_timestamp = Timestamp()
    message_timestamp = datetime.datetime.fromisoformat(timestamp)
    mtime_timestamp.FromDatetime(message_timestamp.replace(tzinfo=datetime.timezone.utc))
    return mtime_timestamp


def infer_func_pb_type(func: FuncTyping) -> T.Type[Message]:
    """
    Infers the message type based on the function signature.
    It assumes the message type is the first parameter.
    """
    # Get the function's signature to inspect the message type
    signature = inspect.signature(func)  # type: ignore
    parameters = list(signature.parameters.values())
    index = 1 if parameters and parameters[0].name == "self" else 0  # Skip `self` for class methods
    message_param = list(signature.parameters.values())[index]
    # We'll assume the message type is hinted in the function's signature
    message_type: T.Type[Message] = message_param.annotation

    assert issubclass(
        message_type, Message
    ), "Message type must be a subclass of google.protobuf.Message"

    return message_type


def find_message_in_args(args: T.Tuple[T.Any, ...], kwargs: T.Dict[str, T.Any]) -> T.Any:
    """
    Finds the message in the arguments and keyword arguments.
    It assumes the message is the first argument or the first keyword argument.
    It pops the message from the arguments and keyword arguments.
    """
    for i, arg in enumerate(args):
        if isinstance(arg, dict) and "data" in arg:
            args = args[:i] + args[i + 1 :]
            return arg, args, kwargs

    for key, value in kwargs.items():
        if isinstance(value, dict) and "data" in value:
            del kwargs[key]
            return value, args, kwargs

    return None, args, kwargs


def deserialize_checks(channel: str, message_pb: Message, warn_latency: bool = True) -> bool:
    if hasattr(message_pb, "utime") and isinstance(message_pb.utime, Timestamp):
        message_timestamp = message_pb.utime.seconds + message_pb.utime.nanos / 1_000_000_000
        current_time = time.time()
        time_diff = current_time - message_timestamp
        if time_diff > MAX_PUBLISH_LATENCY_TIME and warn_latency:
            path_name = get_backtrace_file_name(LATENCY_BACKTRACE_FRAME)
            log.print_warn(
                f"Message publish latency for {path_name}:{channel} "
                f"is too high: {time_diff:.2f} seconds"
            )
            return False

    return True


def _message_handler(func: FuncTyping, warn_latency: bool = True) -> T.Any:
    """Internal implementation of message handler decorator"""
    message_type = infer_func_pb_type(func)

    if asyncio.iscoroutinefunction(func):

        @functools.wraps(func)
        async def async_wrapper(self: T.Any, *args: T.Any, **kwargs: T.Any) -> None:
            """
            The wrapper function that deserializes the message, handles logging,
            and calls the original function.
            """
            assert hasattr(self, "verbose"), "Calling module must have a `verbose` attribute"

            message, args, kwargs = find_message_in_args(args, kwargs)

            # Deserialize the message using the inferred type
            deserialized_message_pb = deserialize_message(
                message, message_type, verbose=self.verbose.ipc
            )

            if deserialized_message_pb is None:
                return None  # Early return if deserialization fails

            channel = message.get("channel", b"None").decode("utf-8")
            deserialize_checks(
                channel=channel, message_pb=deserialized_message_pb, warn_latency=warn_latency
            )

            if self.verbose.ipc:
                log.print_normal(
                    f"{self.__class__} Received {message_type.__name__} "
                    f"message:\n{deserialized_message_pb}"
                )
            await func(self, deserialized_message_pb, *args, **kwargs)

        return async_wrapper

    sfunc = T.cast(T.Callable[..., None], func)

    @functools.wraps(sfunc)
    def sync_wrapper(self: T.Any, *args: T.Any, **kwargs: T.Any) -> None:
        """
        The wrapper function that deserializes the message, handles logging,
        and calls the original function.
        """
        assert hasattr(self, "verbose"), "Calling module must have a `verbose` attribute"

        message, args, kwargs = find_message_in_args(args, kwargs)

        # Deserialize the message using the inferred type
        deserialized_message_pb = deserialize_message(
            message, message_type, verbose=self.verbose.ipc
        )

        if deserialized_message_pb is None:
            return None  # Early return if deserialization fails

        channel = message.get("channel", b"None").decode("utf-8")
        deserialize_checks(
            channel=channel, message_pb=deserialized_message_pb, warn_latency=warn_latency
        )

        if self.verbose.ipc:
            log.print_normal(
                f"{self.__class__} Received {message_type.__name__} "
                f"message:\n{deserialized_message_pb}"
            )

        # If the original function is synchronous, call it normally
        return sfunc(self, deserialized_message_pb, *args, **kwargs)

    return sync_wrapper


def message_handler(func: T.Optional[FuncTyping] = None, *, warn_latency: bool = True) -> T.Any:
    """
    A decorator to handle deserialization of a message and logging.
    Can be used as @message_handler or @message_handler(warn_latency=False)
    """
    if func is None:
        return lambda f: _message_handler(f, warn_latency=warn_latency)
    return _message_handler(func, warn_latency=warn_latency)
