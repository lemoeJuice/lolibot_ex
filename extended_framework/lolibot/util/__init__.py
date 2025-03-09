# 由于同时加载util中的所有模块会导致循环引用，所以拆出来之后分别导入
from .. import Payload, websocket, json
import asyncio


# 为每次api调用生成序列号，以识别返回结果的对应关系
class _SequenceGenerator:
    _seq = -1
    _lock = asyncio.Lock()

    @classmethod
    async def next(cls) -> int:
        async with cls._lock:
            cls._seq = (cls._seq + 1) % 2147483647
            return cls._seq + 1  # 不能返回0，不然result存储类的add方法会出问题


class ApiTimeout(Exception):
    pass


class ApiFailure(Exception):
    pass


# 存储api返回的结果，以实现异步操作
class _ResultStore:
    _futures = {}

    @classmethod
    def add(cls, result: Payload) -> None:
        # 注意这个函数并不在命令处理的调用栈中，所以在这里抛出异常并不能被捕获
        seq = result['echo']  # 有出现过api调用失败返回没有echo字段的情况
        if future := cls._futures.get(seq):
            future.set_result(result)

    # 这个原来在__init__下的，现在改为单独配置超时时间，用不到了
    # 可能需要自定义配置
    # api_timeout: int = 8

    @classmethod
    async def fetch(cls, seq: int, timeout_sec: float) -> Payload:
        future = asyncio.get_event_loop().create_future()
        cls._futures[seq] = future
        try:
            # 是否需要使用shield
            return await asyncio.wait_for(future, timeout_sec)
        except asyncio.TimeoutError:
            raise ApiTimeout(f'API call timeout with timeout_sec {timeout_sec}.')
        finally:
            del cls._futures[seq]


# 调用这个函数来实现onebot(v11)接口，接口说明文档可见于https://github.com/botuniverse/onebot-11/
async def _call_onebot_api(action_name: str, params: dict, timeout: float) -> Payload | None:
    seq = await _SequenceGenerator.next()
    # print(f'Calling onebot api {action_name} with seq {seq}...')

    # 基于quart的上下文机制，应当能够自动处理ws连接的调用，不会出现多个连接处理串台发送的情况
    # 如果需要标记每个连接，可以通过websocket.headers['X-Self-ID']获取当前连接实现的qq号
    await websocket.send(json.dumps({'action': f'{action_name}', 'params': params, 'echo': seq}))

    result = await _ResultStore.fetch(seq, timeout)
    if result['status'] == 'failed':
        raise ApiFailure(f'Api call failed with message:\n{result["message"]}')

    # 疑似不是所有api返回都有data字段
    return result.get('data')

# 不能在这里导入各模块的内容，否则从这里导入会导致加载各模块顺序引起循环引用
