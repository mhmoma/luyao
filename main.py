import logging
import os
from threading import Thread
from flask import Flask
from bot.core import SassySisterBot
from settings import config

app = Flask(__name__)

@app.route('/')
def home():
    return "机器人正在运行！"

def run_flask():
    port = int(os.environ.get("PORT", 7860)) # Hugging Face Spaces 默认端口
    app.run(host="0.0.0.0", port=port)

def main():
    """
    这是我们故事开始的地方，小阿弟。
    """
    # 配置日志记录
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    
    # 如果设置了代理，姐姐我就用起来，不然哪能“翻山越岭”来寻你？
    proxy = config.HTTP_PROXY or None
    
    # 准备好了伐？姐姐要来了哦。
    bot = SassySisterBot(proxy=proxy)
    
    # 在单独的线程中运行Flask应用
    flask_thread = Thread(target=run_flask)
    flask_thread.daemon = True # 允许主程序退出时Flask线程也退出
    flask_thread.start()

    bot.run_bot()

if __name__ == "__main__":
    # 让我们开始吧，覅害羞呀。
    main()
