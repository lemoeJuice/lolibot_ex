from extended_framework.command import on_command
from extended_framework.lolibot.message import MessageEvent


@on_command('bot', cmd_names=['哈喽'])
async def _(event: MessageEvent):
    await event.send('在的哦')
