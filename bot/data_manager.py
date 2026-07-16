import json
import os
import asyncio
from typing import Any, Dict, Optional, Tuple
from datetime import datetime, timezone

FAVOR_MAX = 100

class DataManager:
    """一个用来管理机器人数据的类，比如设置和用户信息。"""

    def __init__(self, data_file: str):
        self.data_file = data_file
        self.data: Dict[str, Any] = self._load_data()
        self._lock = asyncio.Lock()

    def _load_data(self) -> Dict[str, Any]:
        """从 JSON 文件加载数据。如果文件不存在，就返回一个默认的空结构。"""
        if os.path.exists(self.data_file):
            try:
                with open(self.data_file, 'r', encoding='utf-8') as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError) as e:
                print(f"读取数据文件 '{self.data_file}' 的时候出错了: {e}。我会用一个空的设置开始。")
                return self._get_default_data()
        else:
            print(f"没找到数据文件 '{self.data_file}'。我会创建一个新的。")
            return self._get_default_data()

    def _get_default_data(self) -> Dict[str, Any]:
        """返回一个默认的数据结构。"""
        return {
            "bot_settings": {
                "proactive_chat_enabled": True
            },
            "user_data": {}
        }

    def _write_data_file(self):
        try:
            with open(self.data_file, 'w', encoding='utf-8') as f:
                json.dump(self.data, f, indent=4, ensure_ascii=False)
        except IOError as e:
            print(f"保存数据到 '{self.data_file}' 的时候出错了: {e}")

    async def _save_data(self):
        """异步地把当前数据保存到 JSON 文件里。"""
        async with self._lock:
            self._write_data_file()

    def get_setting(self, key: str, default: Any = None) -> Any:
        """从 bot_settings 里拿一个设置项。"""
        return self.data.get("bot_settings", {}).get(key, default)

    async def set_setting(self, key: str, value: Any):
        """在 bot_settings 里设置一个项，然后保存到文件。"""
        if "bot_settings" not in self.data:
            self.data["bot_settings"] = {}
        self.data["bot_settings"][key] = value
        await self._save_data()

    def get_user_data(self, user_id: str) -> Dict[str, Any]:
        """根据用户 ID 拿到这个用户的数据。"""
        return self.data.get("user_data", {}).get(user_id, {})

    async def set_user_data(self, user_id: str, data: Dict[str, Any]):
        """设置某个用户的用户数据，然后保存到文件。"""
        if "user_data" not in self.data:
            self.data["user_data"] = {}
        self.data["user_data"][user_id] = data
        await self._save_data()

    def _utc_now_iso(self) -> str:
        return datetime.now(timezone.utc).isoformat()

    def _ensure_user_record(self, user_id: str) -> Dict[str, Any]:
        if "user_data" not in self.data:
            self.data["user_data"] = {}
        if user_id not in self.data["user_data"]:
            self.data["user_data"][user_id] = {}
        return self.data["user_data"][user_id]

    def get_user_favor_state(self, user_id: str) -> Dict[str, Any]:
        """
        获取用户好感状态（只读，非原子更新）。
        结构（字段可能缺省）：
          favor: int (>=0)
          stage: str
          total_messages: int
          last_message_at: str (ISO)
          favor_events: list[dict]
        """
        user = self.get_user_data(str(user_id))
        favor = int(user.get("favor", 0) or 0)
        if favor < 0:
            favor = 0
        if favor > FAVOR_MAX:
            favor = FAVOR_MAX
        return {
            "favor": favor,
            "stage": str(user.get("stage", "cold") or "cold"),
            "total_messages": int(user.get("favor_total_messages", 0) or 0),
            "last_message_at": user.get("favor_last_message_at"),
            "events": list(user.get("favor_events", []) or []),
        }

    async def apply_favor_delta(
        self,
        user_id: str,
        delta: int,
        reason: str,
        message_snippet: str = "",
        stage: Optional[str] = None,
        max_events: int = 20,
    ) -> Tuple[int, int]:
        """
        对用户好感做一次原子更新，并写入事件记录。
        返回 (favor_before, favor_after)。
        """
        user_id_str = str(user_id)
        async with self._lock:
            user = self._ensure_user_record(user_id_str)

            favor_before = int(user.get("favor", 0) or 0)
            if favor_before < 0:
                favor_before = 0
            favor_after = favor_before + int(delta or 0)
            if favor_after < 0:
                favor_after = 0
            if favor_after > FAVOR_MAX:
                favor_after = FAVOR_MAX

            user["favor"] = favor_after
            if stage is not None:
                user["stage"] = stage

            user["favor_total_messages"] = int(user.get("favor_total_messages", 0) or 0) + 1
            user["favor_last_message_at"] = self._utc_now_iso()

            events = list(user.get("favor_events", []) or [])
            events.append(
                {
                    "at": self._utc_now_iso(),
                    "delta": int(delta or 0),
                    "reason": str(reason or "unknown"),
                    "snippet": (message_snippet or "")[:120],
                    "before": favor_before,
                    "after": favor_after,
                }
            )
            if max_events > 0 and len(events) > max_events:
                events = events[-max_events:]
            user["favor_events"] = events

            self._write_data_file()
            return favor_before, favor_after

    def get_user_thread_id(self, user_id: str) -> Optional[int]:
        """根据用户 ID 拿到这个用户的作品集帖子 ID。"""
        user_data = self.get_user_data(str(user_id))
        return user_data.get("artwork_thread_id")

    async def set_user_thread_id(self, user_id: str, thread_id: int):
        """设置某个用户的作品集帖子 ID，然后保存到文件。"""
        user_id_str = str(user_id)
        if "user_data" not in self.data:
            self.data["user_data"] = {}
        if user_id_str not in self.data["user_data"]:
            self.data["user_data"][user_id_str] = {}
        self.data["user_data"][user_id_str]["artwork_thread_id"] = thread_id
        await self._save_data()

# 创建一个全局实例，这样整个机器人都可以用它
data_manager = DataManager("data.json")
