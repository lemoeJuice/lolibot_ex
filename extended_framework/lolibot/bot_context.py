from contextvars import ContextVar

# 定义 `ContextVar`，用于存储当前 bot 实例
current_bot: ContextVar['Bot'] = ContextVar('current_bot')

from datetime import datetime


def print_log(content: str):
    now = datetime.now()
    datetime_str = now.strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
    bot = current_bot.get()
    print(f'[{datetime_str}] {bot.name}:\n{content}\n')
