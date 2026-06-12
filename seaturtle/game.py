from enum import Enum, auto

class GameStatus(Enum):
    """我们游戏进行到哪一步了呀？"""
    WAITING_FOR_START = auto()  # 等着你喊开始哦
    WAITING_FOR_GUESS = auto()  # 等着你猜呀
    GAME_OVER = auto()          # 游戏结束啦

class SeaTurtleGame:
    """
    这就是我们的海龟汤游戏桌，小阿弟。
    """
    def __init__(self, soup: str, answer: str, owner_id: int):
        self.soup = soup          # 汤面，吊你胃口的
        self.answer = answer      # 汤底，不能轻易让你晓得
        self.owner_id = owner_id  # 是哪个小可爱开了这局游戏
        self.status = GameStatus.WAITING_FOR_START
        self.guesses = []         # 你猜过些啥，姐姐我都记着呢

    def start_game(self):
        """好了，游戏开始哉！"""
        if self.status == GameStatus.WAITING_FOR_START:
            self.status = GameStatus.WAITING_FOR_GUESS
            return f"海龟汤游戏开始啦！\n\n**汤面是：**\n> {self.soup}\n\n现在可以开始猜了呀，小阿弟。你问，我只答‘是’、‘否’、‘无关’哦。"
        return "游戏已经开始哉，覅急呀。"

    def make_guess(self, user_id: int, guess: str) -> str:
        """
        让姐姐我听听看，你又想到了啥个。
        """
        if self.status != GameStatus.WAITING_FOR_GUESS:
            return "游戏还没开始，或者已经结束哉，你急啥个啦。"
        
        # 猜中了汤底，你好聪明呀！
        if guess.strip() == self.answer.strip():
            self.status = GameStatus.GAME_OVER
            return f"恭喜你呀，小阿弟！猜对哉！\n\n**汤底就是：**\n> {self.answer}\n\n你可真厉害，姐姐我好欢喜你呀。"
        
        self.guesses.append((user_id, guess))
        # 这里只是记录下来，具体的回答要靠璐瑶姐姐的“大脑”哦
        return None # 返回 None，表示需要 AI 来判断

    def end_game(self) -> str:
        """
        不想玩啦？那好吧。
        """
        if self.status == GameStatus.GAME_OVER:
            return "游戏已经结束哉。"
        
        self.status = GameStatus.GAME_OVER
        return f"好吧，既然你不想玩了，那就算了呀。\n\n**汤底是：**\n> {self.answer}\n\n下次再陪姐姐我玩哦。"
