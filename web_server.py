import os
import webbrowser
from threading import Timer

import uvicorn

from web_api import app

HOST = "127.0.0.1"
PORT = int(os.environ.get("EBOOK_TOOLBOX_PORT", "8000"))
URL = f"http://{HOST}:{PORT}"


def open_browser():
    webbrowser.open_new(URL)


if __name__ == "__main__":
    print(f"启动 Ebook Toolbox Web 服务，请访问 {URL}")
    # 启动器已经自己开过浏览器了，避免开两个标签页。
    if os.environ.get("EBOOK_TOOLBOX_NO_BROWSER") != "1":
        Timer(1.5, open_browser).start()
    # 仅监听本机回环地址，不对外暴露：本服务没有任何鉴权。
    uvicorn.run(app, host=HOST, port=PORT)
