from extended_framework.lolibot import Bot, Server
from extended_framework.command import handle_msg

if __name__ == '__main__':
    server = Server()

    main = Bot('main', '/').load_plugins_from_folder('example_plugins')
    main.handle_msg_funcs.append(handle_msg())

    # 可以根据需要在一个server对象上挂多个bot
    server.add_bot(main).run()
