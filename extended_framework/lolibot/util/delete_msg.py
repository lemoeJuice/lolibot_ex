from . import _call_onebot_api
from ..message import MessageEvent


async def delete_msg(event: MessageEvent) -> None:
    # 需要校验是否有撤回权限
    msg_id = event.message_id
    await _call_onebot_api('delete_msg_async', {'message_id': msg_id}, 5)
