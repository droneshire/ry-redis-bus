# from pb_types.example_pb2 import ExamplePb  # pylint: disable=no-name-in-module
import typing as T

from google.protobuf.message import Message


class Channel:
    REQUIRED_FIELDS = ["utime"]

    def __init__(self, name: str, msg_type: T.Type[Message] | None) -> None:
        self.name = name
        self.pb_type = msg_type or Message

        if msg_type is None or msg_type == Message:
            return

        msg_instance = msg_type()
        for field in self.REQUIRED_FIELDS:
            if hasattr(msg_instance, field):
                continue
            raise AttributeError(f"{msg_type} does not have a {field} field")

    def __repr__(self) -> str:
        return self.name

    def __str__(self) -> str:
        return self.name

    def __eq__(self, other: object) -> bool:
        if isinstance(other, str):
            return self.name == other
        if isinstance(other, Channel):
            return self.name == other.name
        return False

    def __hash__(self) -> int:
        return hash(self.name)
