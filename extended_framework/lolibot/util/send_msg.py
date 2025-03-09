from . import _call_onebot_api
from ..message import Position, Message
from ..bot_context import print_log

import asyncio


# 先前为了防止循环引用，send_msg移动至type.py，当前采用的方案是把util各项分开
# 可能需要调整架构，或者把MessageEvent做二次封装等

# 这个是直接搬过来的
# 为每次api调用生成序列号，以识别返回结果的对应关系
class _SequenceGenerator:
    _seq = -1
    _lock = asyncio.Lock()

    @classmethod
    async def next(cls) -> int:
        async with cls._lock:
            cls._seq = (cls._seq + 1) % 2147483647
            return cls._seq + 1  # 不能返回0，不然result存储类的add方法会出问题


async def send_msg(position: Position, message: Message | str) -> int:
    content = message.content if isinstance(message, Message) else message
    params = {'message_type': 'group', 'group_id': position.obj_id, 'message': content} if position.is_group \
        else {'message_type': 'private', 'user_id': position.obj_id, 'message': content}
    temp_id = await _SequenceGenerator.next()
    print_log(f'Sending Message No.{temp_id} to {position}:\n{message}')
    res = await _call_onebot_api('send_msg_async', params, timeout=12)
    msg_id = res['message_id']
    print_log(f'Message No.{temp_id} sent successfully with real msg_id {msg_id}.')
    return msg_id
