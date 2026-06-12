import sys
import os

# 将项目根目录添加到 sys.path
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

import logging
import os
from bot.core import SassySisterBot
from settings import config

def main():
    """
    这是我们故事开始的地方，小阿弟。
    """
    # 配置日志记录
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    
    # 准备好了伐？姐姐要来了哦。
    bot = SassySisterBot()
    
    bot.run_bot()

if __name__ == "__main__":
    # 让我们开始吧，覅害羞呀。
    main()
