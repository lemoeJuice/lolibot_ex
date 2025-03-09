########################################################################################################################
# 下面的具体封装不一定为标准内容，根据协议端本身的格式做了一定修改
# 目前暂时只处理message，且api并未使用快速操作

# 不一定存在的字段采用.get方法，大部分字段分情况讨论时可以确定是否存在

########################################################################################################################
class Sender:  # MessageEvent类的数据成员
    def __init__(self, source: dict):
        self.group_id: int | None = source.get('group_id')
        # private：friend、group、other/group：owner、admin、member
        self.role: str = source['sender']['role'] if self.group_id else source['sub_type']
        self.user_id: int = source['sender']['user_id']
        self.nickname: str = source['sender']['nickname']
        self.card: str = source['sender']['card']  # 群名片/备注，如果没有设置就是空字符串

    def __eq__(self, other):  # 判断是否同一个用户在同一语境下
        if not isinstance(other, Sender):
            return NotImplemented
        return self.group_id == other.group_id and self.user_id == other.user_id

    def __str__(self):
        group_info = f'group_id={self.group_id}' if self.group_id else 'private'
        return f"Sender({group_info}, role:{self.role}, user_id:{self.user_id}, nickname:{self.nickname}{', card:' + self.card if self.card else ''})"


class Position:
    def __init__(self, obj_id: int, is_group: bool):
        self.obj_id = obj_id
        self.is_group = is_group

    def __eq__(self, other):  # 判断是否同一个用户在同一语境下
        if not isinstance(other, Position):
            return NotImplemented
        return self.is_group == other.is_group and self.obj_id == other.obj_id

    def __hash__(self):  # 确保哈希值与 __eq__ 逻辑一致
        return hash((self.obj_id, self.is_group))


class Group(Position):
    def __init__(self, group_id: int):
        super().__init__(group_id, True)

    def __str__(self):
        return f'Group {self.obj_id}'


class Private(Position):
    def __init__(self, qq_id: int):
        super().__init__(qq_id, False)

    def __str__(self):
        return f'User {self.obj_id}'


########################################################################################################################
from io import BytesIO


# 内部属性可以改用property
class Message:
    def __init__(self, *args: '_MessageSegment'):
        self.content = list(args)
        self.text = None

    def __str__(self):
        return "[" + ", ".join(str(segment) for segment in self.content) + "]"

    def insert_at_front(self, seg: '_MessageSegment'):
        self.content.insert(0, seg)
        return self

    # 逻辑需要修改以适应命令的解析流程
    def get_plain_text(self) -> str:
        if self.text is None:  # 命令解析有可能导致为空字符串
            res = ''
            for seg in self.content:
                if temp := seg.get_plain_text():
                    res += temp.strip()
                    res += ' '
            self.text = res[:-1]  # 去掉最后的空格
        return self.text

    def get_at_qq(self) -> list[int]:
        res = []
        for seg in self.content:
            if temp := seg.get_at_qq():
                res.append(temp)
        return res

    def get_reply_id(self) -> int | None:  # 如果是回复消息那回复一定在最前面（对吗？）
        return self.content[0].get_reply_id()

    async def get_image_route(self) -> list[BytesIO]:
        res = []
        for seg in self.content:
            if temp := await seg.get_image_route():
                res.append(temp)
        return res

    async def get_file_route(self) -> str | None:  # 文件一定只有一个消息段元素
        return await self.content[0].get_file_route()


########################################################################################################################
class _Captured(Exception):
    pass


class ResponseTimeout(Exception):
    pass


# 需要减少耦合
from .util.send_msg import send_msg
from .bot_context import print_log

import asyncio

from typing import Callable


class MessageEvent:
    expect_dict = {}  # 用于提供多轮命令对话支持，可以直接读取内容并抛出ResponseTimeout来取消

    async def expect(self, verify_func: Callable[['MessageEvent'], bool],
                     timeout_sec: int):  # 这里的验证函数应当是根据具体情况定义的内部函数，不会有相同的内存地址
        future = asyncio.get_event_loop().create_future()
        MessageEvent.expect_dict[verify_func] = future

        try:
            self.__dict__ = await asyncio.wait_for(future, timeout_sec)
        except asyncio.TimeoutError:
            raise ResponseTimeout(f'Response not received with timeout_sec {timeout_sec}.')
        finally:
            del MessageEvent.expect_dict[verify_func]

    def _check_expect(self):
        flag = False
        for verify_func in list(MessageEvent.expect_dict):  # 防止一遍修改一边遍历导致问题
            if verify_func(self):  # 考虑是否需要break，即保证一次只能触发一条命令继续处理
                MessageEvent.expect_dict[verify_func].set_result(self.__dict__)
                flag = True
        return flag

    # 提供几个用于expect检查的方法

    def same_sender(self):
        def checker(new: 'MessageEvent'):
            return new.sender == self.sender

        return checker

    def same_context(self):
        def checker(new: 'MessageEvent'):
            if self.sender.group_id:
                return self.sender.group_id == new.sender.group_id
            else:
                return not new.sender.group_id and self.sender.user_id == new.sender.group_id

        return checker

    def __init__(self, source: dict):
        if source['message_format'] != 'array':
            raise Exception('当前只接受array格式的消息，请在协议端中配置消息格式为array.')

        # 丢弃固定的message_format,post_type，如果需要标记客户端连接则需要加载self_id
        self.self_id = source['self_id']

        # 目前疑似没有匿名功能，后端似乎也不支持，丢弃anonymous字段

        # 消息标识相关
        # self.time: int = source['time']  # 目前暂时没有对这一字段的需求，且可以通过time获取
        self.message_id: int = source['message_id']  # message_seq,real_id字段似乎携带相同信息，将其丢弃

        # 权限控制相关
        self.sender = Sender(source)
        # 隐含message_type，如果是私聊消息group_id就是None
        # user_id属性已在sender中包含
        # 由于群聊仅支持normal，将sub_type合并到sender
        # self.sub_type: str = source['sub_type']  # friend、group、other/normal、anonymous、notice

        # 消息内容相关
        self.message = Message(*list(_MessageSegment(item) for item in source['message']))
        # 这两个不知道用不用得到，先丢了
        # self.font = source['font']
        # self.raw_message = source['raw_message']

        # print(f'\nReceived {self}')
        print_log(f'Message id {self.message_id} received from {self.sender}:\n{self.message}')

        if self._check_expect():
            print_log('Message Captured.')
            raise _Captured

    # def __str__(self):
    #     return f'Message(time={self.time}, msg_id={self.message_id}, sender={self.sender}, message={self.message})'

    @property
    def position(self) -> Position:
        if gid := self.sender.group_id:  # 群号不会为0
            return Group(gid)
        else:
            return Private(self.sender.user_id)

    async def send(self, message: Message | str, *, reply: bool = True, at_sender: bool = True):
        # 暂不清楚file的发送限制，是否可以加at或者reply或者一次发多个
        if isinstance(message, Message):
            if isinstance(message.content[0], File):
                reply = False
                at_sender = False
                asyncio.create_task(self.send('正在发送文件...'))
            elif isinstance(message.content[0], Reply):  # 解决一条消息里面发两个回复会爆炸的问题，但需要注意expect的替换特性
                reply = False
        else:
            message = Message(Text(message))

        if at_sender and self.sender.group_id:
            first_seg = message.content[0]
            if first_seg.type == 'text':
                first_seg.data['text'] = f" {first_seg.data['text']}"
            message.insert_at_front(At(self.sender.user_id))
        if reply:
            message.insert_at_front(Reply(self.message_id))

        return await send_msg(self.position, message)


########################################################################################################################
import base64
from typing import BinaryIO


def bytes2base64str(self: BinaryIO) -> str:
    current_pos = self.tell()  # 记录当前指针位置
    self.seek(0)  # 将指针移动到文件开头
    data = self.read()  # 读取全部数据
    self.seek(current_pos)  # 恢复指针位置
    return 'base64://' + base64.b64encode(data).decode('utf-8')


from .util.get_image import get_image
from .util.get_file import get_file


class _MessageSegment(dict):  # 是否需要在接收消息时直接构造子类对象？
    def __init__(self, source: dict):
        super().__init__(source)
        self.type: str = self['type']
        self.data: dict = self['data']

    def __str__(self):
        return f"{self.type}({self.data})"

    def get_plain_text(self) -> str | None:
        if self.type == 'text':
            return self.data['text'].strip()

    def get_at_qq(self) -> int | None:
        if self.type == 'at':
            return int(self.data['qq'])

    def get_reply_id(self) -> int | None:
        if self.type == 'reply':
            return self.data['id']

    # 注意该方法不能作用于子类手动构造的image对象上，否则会引发异常
    async def get_image_route(self) -> BytesIO | None:
        if self.type == 'image':
            return BytesIO(await get_image(self.data['url']))

    # 注意该方法不能作用于子类手动构造的file对象上，否则会引发异常
    async def get_file_route(self) -> str | None:
        if self.type == 'file':
            return await get_file(self.data['file_id'])


class Text(_MessageSegment):
    def __init__(self, text: str):
        super().__init__({'type': 'text', 'data': {'text': text}})


class At(_MessageSegment):
    def __init__(self, qq_id: int):
        super().__init__({'type': 'at', 'data': {'qq': f'{qq_id}'}})


class Reply(_MessageSegment):
    def __init__(self, msg_id: int):
        super().__init__({'type': 'reply', 'data': {'id': f'{msg_id}'}})


class Image(_MessageSegment):
    def __init__(self, file: BinaryIO):
        super().__init__({'type': 'image', 'data': {'file': bytes2base64str(file)}})

    def __str__(self):
        return 'Image'


class File(_MessageSegment):
    def __init__(self, file: str):
        super().__init__({'type': 'file', 'data': {'file': file}})

    def __str__(self):
        return 'File'


########################################################################################################################
__all__ = [
    'Message',
    'MessageEvent',
    'ResponseTimeout',

    'Text',
    'Image',
    'At',
    'Reply',
    'File'
]

########################################################################################################################
