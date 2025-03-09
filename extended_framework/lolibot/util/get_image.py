# 由于不同版本的协议端获取图片不一定都能正常工作，且为了避免额外的硬盘io开销，手动实现了这个接口
from urllib.parse import urlparse, parse_qs
import aiohttp

import asyncio
import atexit


class HttpClient:
    def __init__(self):
        self._session = None  # 创建全局 session
        atexit.register(self.close_sync)  # 在程序结束时自动关闭

    @property
    def session(self):
        if not self._session:
            self._session = aiohttp.ClientSession(trust_env=True)
        return self._session

    async def close(self):
        if not self.session.closed:
            await self.session.close()

    def close_sync(self):
        """同步调用 close()，确保 session 在 Python 退出前关闭"""
        loop = asyncio.get_event_loop()
        if loop.is_running():
            loop.create_task(self.close())  # 适用于异步环境
        else:
            loop.run_until_complete(self.close())  # 适用于同步环境


client = HttpClient()


def parse_url(url: str):
    parsed = urlparse(url)
    image_url = f'http://{parsed.netloc}{parsed.path}'
    query = parse_qs(parsed.query)
    return image_url, query


headers = {
    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.36',
    'Referer': 'https://multimedia.nt.qq.com.cn/'
}


async def get_image(url: str):
    image_url, query = parse_url(url)

    try:
        async with client.session.get(image_url, params=query, headers=headers) as resp:
            resp.raise_for_status()
            return await resp.read()
    except aiohttp.ClientResponseError as e:
        try:
            content = await resp.text()
        except:
            content = "<Response content is not text>"
        raise Exception(f"Error downloading file from {image_url}: {e}\nStatus code: {e.status}\nContent: {content}")
    except Exception as e:
        raise Exception(f"An unexpected error occurred while downloading file from {image_url}: {e}")
