from . import _call_onebot_api


# 有的协议端会自动清理文件缓存
# 如果文件过大可能会超时
async def get_file(file_id: str) -> str:
    res = await _call_onebot_api('get_file_async', {'file_id': file_id}, 120)
    return res['file']  # 还有一个url字段，但是和file是一样的
