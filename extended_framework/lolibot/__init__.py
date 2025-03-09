from quart import Quart, websocket
import uvicorn

try:
    import ujson as json  # 速度比python原生json库更快，但不支持非标准格式
except ImportError:
    import json

from typing import Dict, Self, List, Callable

Payload = Dict[str, int | str | Self]

from .message import MessageEvent, _Captured
from .bot_context import current_bot, print_log

# 这两个装饰器由于在多个机器人共用同一处理逻辑时会导致潜在的问题，建议谨慎使用
# 可以参考实现逻辑手动添加处理函数

# # 将函数装饰为反向websocket连接建立时调用的函数
# def on_wsr_connection(func: Callable[[], None]):
#     bot = current_bot.get()
#     bot.handle_wsr_connection_funcs.append(func)
#     return func
#
#
# # 将函数装饰为消息处理函数
# def on_message(func: Callable[[MessageEvent], None]):
#     bot = current_bot.get()
#     bot.handle_msg_funcs.append(func)
#     return func  # 这里的return并无必要，只是为了留出扩展性


import importlib
import os
import traceback


def _load_plugins_from_list(plugin_routes: list[tuple[str, str]]):
    for module in plugin_routes:
        module_name, module_route = module
        try:
            importlib.import_module(module_route)
            print_log(f'Successfully loaded plugin {module_name}.')
        except:
            print_log(f'Error while loading plugin {module_name}:\n{traceback.format_exc()}')


def find_modules(plugin_folder: str, prefix: str = ''):
    to_import: list[tuple[str, str]] = []

    for filename in os.listdir(plugin_folder):
        file_path = os.path.join(plugin_folder, filename)

        # 将路径转换为模块名时，使用 os.path.sep 动态替换
        normalized_folder = plugin_folder.replace(os.path.sep, '.')

        # 检查是否是Python文件
        if filename.endswith('.py') and filename != '__init__.py':
            filename = filename[:-3]
            to_import.append((f'{prefix}{filename}', f'{normalized_folder}.{filename}'))

        # 检查是否是包
        elif os.path.isdir(file_path):
            to_import.extend(find_modules(file_path, f'{prefix}{filename}.'))

    return to_import


from .util import _ResultStore
import asyncio


# bot类，此类应当实现bot的配置以及命令处理逻辑，并通过将bot绑定到server的端点来激活命令处理，以实现在不同的端点提供不同的插件
# 多bot场景下要注意日志的标记以及命令的单一触发
class Bot:
    # 传入参数为客户端配置的反向ws端点，如果遇到连接问题请务必确认严格匹配（注意最后的斜杠），可以参考仓库中的测试用例填写
    def __init__(self, name: str, endpoint: str):
        self.name = name
        self.endpoint = endpoint
        self.handle_wsr_connection_funcs: List[Callable[[], None]] = []
        self.handle_msg_funcs: List[Callable[[MessageEvent], None]] = []

    def load_plugins_from_list(self, plugin_routes: list[tuple[str, str]]):
        bot_token = current_bot.set(self)
        print_log('Waiting for plugins to be loaded...')
        _load_plugins_from_list(plugin_routes)
        current_bot.reset(bot_token)  # 注意如果上面抛出异常会导致问题
        return self

    def load_plugins_from_folder(self, plugin_folder: str):
        return self.load_plugins_from_list(find_modules(plugin_folder))

    # 当有客户端连接时quart框架会自动调用这个函数
    # 目前主流的客户端都是universal形式提供
    async def _handle_wsr_conn(self) -> None:
        role = websocket.headers['X-Client-Role'].lower()
        if role != 'universal':
            raise Exception('目前不支持universal客户端以外的连接形式.')

        while True:
            payload = json.loads(await websocket.receive())

            if post_type := payload.get('post_type'):  # event推送，不会出现空字符串因此可以直接if
                self._handle_event_func(payload, post_type)
            else:  # api响应
                _ResultStore.add(payload)

    def _handle_event_func(self, payload: Payload, post_type: str) -> None:
        bot_token = current_bot.set(self)

        # 如果需要在一个后端挂多个bot实现守护，可以在这里加上对心跳包的检测

        if post_type == 'message':
            try:
                self._on_message(MessageEvent(payload))
            except _Captured:
                return
        elif post_type == 'meta_event':
            if payload.get('meta_event_type') == 'lifecycle' and payload.get('sub_type') == 'connect':
                self._on_wsr_connection()

        current_bot.reset(bot_token)  # 注意异常可能导致上下文恢复的缺失

    def _on_wsr_connection(self) -> None:
        for func in self.handle_wsr_connection_funcs:
            asyncio.create_task(func())

    # 注意如果有多个处理函数，需要避免修改event对象导致问题，如果出现问题可以考虑加锁或者传递拷贝
    def _on_message(self, event: MessageEvent) -> None:
        for func in self.handle_msg_funcs:
            asyncio.create_task(func(event))


# server类，封装了quart应用提供基于反向ws连接的消息收发功能，创建该类的实例并调用run方法以使用uvicorn启动服务
# 启动方式有待改进，考虑是bot类方法传入server对象还是server添加bot，还是添加外部函数接受bot对象并创建server
class Server:
    def __init__(self, *, import_name: str = __name__, **server_app_kwargs):
        self._server_app = Quart(import_name, **server_app_kwargs)

    def run(self, host: str = '127.0.0.1', port: int = 8082, *args, **kwargs) -> None:
        if 'log_config' not in kwargs:
            kwargs['log_config'] = None
        print(f'Starting service on {host}:{port}...\n')
        uvicorn.run(self._server_app, host=host, port=port, *args, **kwargs)

    def add_bot(self, bot: Bot):
        self._server_app.add_websocket(bot.endpoint, view_func=bot._handle_wsr_conn, endpoint=f'{bot.endpoint}_ws')
        return self
