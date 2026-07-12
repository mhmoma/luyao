import sys
import os

# 将项目根目录添加到 sys.path
sys.path.insert(0, os.path.abspath(os.path.dirname(__file__)))

import logging
import os
from bot.core import SassySisterBot
from settings import config

def main():
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    bot = SassySisterBot()
    bot.run_bot()

if __name__ == "__main__":
    main()
