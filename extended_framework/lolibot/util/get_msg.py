from . import _call_onebot_api
from ..message import MessageEvent


async def get_msg(msg_id: int) -> MessageEvent:
    source = await _call_onebot_api('get_msg_async', {'message_id': msg_id}, 5)
    return MessageEvent(source)
