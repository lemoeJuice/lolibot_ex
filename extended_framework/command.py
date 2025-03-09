from .lolibot.message import *
from .lolibot import Bot, current_bot, print_log  # , on_wsr_connection, on_message
# 使用current_bot以适配多个bot的命令隔离

import asyncio
import random
import traceback

from typing import Container, Dict, List, Callable, Awaitable


# 这一部分需要修改
class Permission:
    # 是否统一格式为from_funcs，同时禁止直接使用类名构造而只能通过方法构造，拆分为两个类
    def __init__(self, *check_perm_funcs: Callable[[MessageEvent], bool]):
        self.check_perm_funcs = check_perm_funcs

    def check(self, event: MessageEvent) -> bool:
        if not self.check_perm_funcs:
            return True
        return any(func(event) for func in self.check_perm_funcs)

    # 下面提供了两个基于白名单的权限检查对象

    @staticmethod
    def allow_user(*user_ids: int) -> 'Permission':
        def checker(event: MessageEvent):
            return event.sender.user_id in user_ids

        return Permission(checker)

    @staticmethod
    def allow_group(*group_ids: int) -> 'Permission':
        def checker(event: MessageEvent):
            return event.sender.group_id in group_ids

        return Permission(checker)

    @staticmethod
    def simple_allow_list(*, user_ids: Container[int] = ...,
                          group_ids: Container[int] = ...,
                          reverse: bool = False) -> 'Permission':
        user_ids = user_ids if user_ids is not ... else set()
        group_ids = group_ids if group_ids is not ... else set()

        def checker(event: MessageEvent) -> bool:
            is_in = event.sender.user_id in user_ids or event.sender.group_id in group_ids
            return not is_in if reverse else is_in

        return Permission(checker)


# 由于多个bot存在时使用装饰器会导致只有一个bot导入这个，所以暂时采用手动添加消息处理函数的方案
# @on_message
# async def handle_msg(event: MessageEvent) -> None:
#     if _handle_command(event):
#         return
#     if test_perm.check(event):  # 这个check是否需要写成event类的方法
#         await handle_common_msg(event)

def handle_msg(*allow_process_common_msg_groups: int):
    if not allow_process_common_msg_groups:
        async def _(event: MessageEvent) -> None:
            _handle_command(event)

    else:
        perm = Permission.allow_group(*allow_process_common_msg_groups)

        async def _(event: MessageEvent) -> None:
            if _handle_command(event):
                return
            if perm.check(event):  # 这个check是否需要写成event类的方法
                await handle_common_msg(event)

    return _


repeat_rate: float = 0.08


# 权限需要自己控制
async def handle_common_msg(event: MessageEvent):
    if to_me(event):
        await talk(event)
    else:
        if random.random() < repeat_rate:
            await repeat(event)


from extended_framework.lolibot.message import Position


async def chat(position: Position, content: str):
    return '干什么！'


async def talk(event: MessageEvent):
    # 可以接入生成式ai来做聊天机器人
    result = await chat(event.position, event.message.get_plain_text())
    await event.send(result)


async def repeat(event: MessageEvent):
    # 需要考虑安全性
    if res := event.message.get_plain_text():
        await event.send(res, reply=False, at_sender=False)


def to_me(event: MessageEvent) -> bool:
    # 私聊默认True，群聊at机器人账号为True
    if not (flag := not event.sender.group_id):
        at_list = event.message.get_at_qq()
        for item in at_list:
            if item == event.self_id:
                flag = True
                break
    return flag


cmd_handler = Callable[[MessageEvent], Awaitable[None]]


# 这个只应该在被on_command装饰的函数中抛出
# 是为了将偏离正常流程的操作区分开，如果模块没有实现细粒度的异常捕获，可以通过在命令执行出错时打印stacktrace来发现问题
class Hint(Exception):
    pass


class Command:
    def __init__(self, main_name: str, func: cmd_handler, cmd_names: List[str], permission: Permission):
        self.name = main_name
        self.func = Command.func_wrapper(func)
        self.cmd = cmd_names
        self.permission = permission

    @staticmethod
    def func_wrapper(func: Callable[[MessageEvent], Awaitable[None]]):
        async def wrapper(event: MessageEvent):
            try:
                await func(event)
            except Hint as e:
                await event.send(str(e))
            except SystemExit:
                raise
            except:
                print_log(traceback.format_exc())
                await event.send('发生了预料之外的错误，请联系bot管理员.')

        return wrapper

    def permission_check(self, event: MessageEvent):
        return self.permission.check(event)

    def execute(self, event: MessageEvent):
        # 可以定义一个集成命令处理器来规范化输出以及错误处理等流程
        asyncio.create_task(self.func(event))


# 下面是自定义的指令注册与解析方式，使用了两层映射，增加了灵活性，但要注意性能问题
# 建立别名到唯一标识的映射
bot_to_alias: Dict['Bot', Dict[str, str]] = {}  # 建立机器人到其命令-别名映射的映射的字典
# 建立唯一标识到命令对象的映射，存储函数的引用
main_name_to_command: Dict[str, Command] = {}


# 装饰器，提供命令的注册与缓存
def on_command(main_name: str, cmd_names: List[str] | None = None, *, permission: Permission = Permission()):
    if cmd_names is None:
        cmd_names = [main_name]
    else:
        cmd_names.append(main_name)

    bot = current_bot.get()
    alias_to_main_name = bot_to_alias.setdefault(bot, {})

    def deco(func: cmd_handler):
        if main_name in main_name_to_command:
            raise Exception(f'命令 {main_name} 已经存在，无法重复注册.')

        # 防止指令名称之间以对方开头，减小指令解析成本
        # 如果需要修改可以建立互相包含的层级链路，解析为匹配的最后一项
        for cmd in cmd_names:
            for item in alias_to_main_name:
                if item.startswith(cmd) or cmd.startswith(item):
                    existing_main = alias_to_main_name[item]
                    raise Exception(f'指令别名 {cmd}({main_name}) 与 {item}({existing_main}) 发生冲突，导入失败.')

        for cmd in cmd_names:
            # 这里比较完之后再进行添加，防止同一指令的几个别名互相冲突或者导入失败后一部分别名残留
            alias_to_main_name[cmd] = main_name

        # 创建并存储命令对象，可以配合permission等模块实现动态修改
        main_name_to_command[main_name] = Command(main_name, func, cmd_names, permission)

        # 函数已经添加到列表，如果不需要在其他地方手动调用则不需要return func
        # 如果需要手动调用，要注意应当调用未被装饰的原始函数，否则可能会导致重复添加（？）

    return deco


# 需要自定义配置，另外是否需要多种开头
# 可能需要指令族，即一组指令有同样的开头
command_start: List[str] = ['']

if command_start:
    if '' in command_start:
        command_start.clear()


def check_command_like(event: MessageEvent) -> bool:
    if not command_start:
        return True

    text = event.message.get_plain_text()
    for start in command_start:
        if text.startswith(start):
            event.message.text = text[len(start):]  # 去掉了strip，即指令起始内容后面要紧接指令，不能有空格
            return True
    return False


# 实际执行的函数，提供从消息事件到命令的解析以及执行
def _handle_command(event: MessageEvent) -> bool:
    # 对于消息的文字部分，检查是否以指令开头
    if not check_command_like(event):
        return False

    # 检查命令是否存在
    text = event.message.get_plain_text()
    bot = current_bot.get()
    alias_to_main_name = bot_to_alias.get(bot, {})

    for alias, main_name in alias_to_main_name.items():
        if text.startswith(alias):
            command = main_name_to_command[main_name]
            # print(f'\nCommand {cmd} triggered. Checking permission...')
            if command.permission_check(event):
                # print(f'\nPermission check pass.')
                # 更新事件消息，去掉命令部分
                event.message.text = text[len(alias):].lstrip()  # 去掉指令正文左边可能存在的空格
                command.execute(event)
                return True
    return False
