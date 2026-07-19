import discord
from discord.ext import commands, tasks
from datetime import datetime, timedelta, timezone
from settings import config
from ai.client import get_chat_completion, get_chat_completion_with_image, download_image, get_image_tags_from_comfyui
from bot.data_manager import data_manager, FAVOR_MAX
from urllib.parse import urlparse
import os
import uuid
import shlex
import random
import aiofiles.os
import asyncio
import re
from typing import Optional, Literal

TEMP_DIR = "temp"
FAVOR_DAILY_GAIN_CAP = 12
FAVOR_POSITIVE_MIN_INTERVAL = 45
FAVOR_EVENT_COOLDOWN_SECONDS = {
    "thanks": 1800,
    "polite": 1200,
    "constructive": 600,
    "shared_image": 1800,
}

class SassySisterBot(commands.Bot):
    def __init__(self, **options):
        # --- 代理设置 ---
        proxy_url = options.pop('proxy', None)
        if proxy_url:
            print(f"姐姐我看到侬个代理了哦: {proxy_url}")

        # --- 机器人意图跟初始化 ---
        intents = discord.Intents.default()
        intents.message_content = True
        
        # 直接把代理 URL 交给 discord.py 来处理
        super().__init__(command_prefix="!", intents=intents, proxy=proxy_url, **options)

        # --- 其他个东西 ---
        self.persona = self._load_persona()
        self._ensure_temp_dir()
        self.proactive_chat_enabled = data_manager.get_setting("proactive_chat_enabled", True)
        self.proactive_chat_probability = config.PROACTIVE_CHAT_PROBABILITY
        self.proactive_cooldown_seconds = config.PROACTIVE_COOLDOWN_SECONDS
        self.artwork_forwarding_enabled = data_manager.get_setting("artwork_forwarding_enabled", True)
        self._channel_locks: dict[int, asyncio.Lock] = {}
        self._last_proactive_at: dict[int, datetime] = {}
    def _ensure_temp_dir(self):
        """为你的作品，准备一个专属的临时画室。"""
        if not os.path.exists(TEMP_DIR):
            os.makedirs(TEMP_DIR)

    def _load_persona(self) -> str:
        """把“璐瑶”姐姐的人设加载到“脑子”里，这样才不会忘了该怎么“疼”你。"""
        try:
            persona_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'persona.md')
            with open(persona_path, 'r', encoding='utf-8') as f:
                return f.read()
        except FileNotFoundError:
            print("哎呀，找不到 persona.md 文件，姐姐我的人设丢了，这可怎么办？")
            return "你是璐瑶。冷，话少，对题，有内容。不装神棍，不发鸡汤。小哈是你的狗，你护它。Tomkk是你唯一亲近的人，只对他更软一点。"

    async def setup_hook(self):
        """初始化钩子，加载 cogs 并同步命令"""
        print("[璐瑶] 加载模块...")
        await self.load_extension("bot.drawing")
        print("[璐瑶] 同步斜杠命令...")
        await self.tree.sync()
        print("[璐瑶] 命令就绪。")
        self.cleanup_channels.start()

    async def _forward_to_artwork_forum(self, author: discord.Member, files: list[discord.File], prompt: Optional[str] = None, negative_prompt: Optional[str] = None):
        """将文件、正面和反向提示词转发到用户的作品集论坛帖子中。"""
        forum_channel_id = 1442460523672109096
        forum_channel = self.get_channel(forum_channel_id)
        
        if not isinstance(forum_channel, discord.ForumChannel):
            print(f"错误：频道 {forum_channel_id} 不是一个论坛频道。")
            return

        thread_name = f"{author.display_name}的作品集"
        target_thread = None
        
        # 1. 优先从数据文件里找帖子 ID
        thread_id = data_manager.get_user_thread_id(author.id)
        if thread_id:
            try:
                target_thread = await self.fetch_channel(thread_id)
                if not isinstance(target_thread, discord.Thread):
                     target_thread = None
            except (discord.NotFound, discord.Forbidden):
                target_thread = None

        # 2. 如果数据里没有，或者帖子没了，就按名字搜索
        if not target_thread:
            for thread in forum_channel.threads:
                if thread.name == thread_name:
                    target_thread = thread
                    break
            if not target_thread:
                try:
                    async for thread in forum_channel.archived_threads(limit=None):
                        if thread.name == thread_name:
                            target_thread = thread
                            break
                except discord.Forbidden:
                    print(f"哎呀，姐姐我没权限看 {forum_channel.name} 里的归档帖子呀。")

        if not files:
            return

        # 3. 发送或创建帖子
        parts = []
        if prompt:
            parts.append(f"**提示词:**\n```{prompt}```")
        if negative_prompt:
            parts.append(f"**反向提示词:**\n```{negative_prompt}```")
        message_content = "\n\n".join(parts)


        if not target_thread:
            try:
                initial_content = f"欢迎来到 {author.mention} 的个人作品集！\n\n{message_content}".strip()
                target_thread, _ = await forum_channel.create_thread(
                    name=thread_name,
                    content=initial_content,
                    files=files
                )
                await data_manager.set_user_thread_id(author.id, target_thread.id)
                print(f"为 {author.display_name} 创建了新的作品集帖子，并保存了 ID。")
            except Exception as e:
                print(f"创建作品集帖子失败: {e}")
        else:
            try:
                if target_thread.archived:
                    await target_thread.edit(archived=False)
                
                # 在消息前加入一个尽可能长的、带表情的自定义分隔符
                separator = "✨ ———————————————————— ✨"
                final_content = f"{separator}\n\n{message_content}" if message_content else separator
                await target_thread.send(content=final_content, files=files)
                print(f"已将图片转发到 {author.display_name} 的作品集。")
            except Exception as e:
                print(f"转发图片到作品集失败: {e}")

    @tasks.loop(minutes=5)
    async def cleanup_channels(self):
        """定期清理指定频道，可根据频道ID应用不同规则。"""
        await self.wait_until_ready()
        if not config.CLEANUP_CHANNEL_IDS:
            return

        channel_ids = [int(cid.strip()) for cid in config.CLEANUP_CHANNEL_IDS.split(',')]
        
        for channel_id in channel_ids:
            channel = self.get_channel(channel_id)
            if channel and isinstance(channel, discord.TextChannel):
                # 统一保留2条消息
                limit = 2
                
                try:
                    # 获取比限制多一条的消息，以此来确定删除的界线
                    history = [msg async for msg in channel.history(limit=limit + 1)]
                    
                    # 如果消息数量大于限制，那么多出来的就都要清理掉
                    if len(history) > limit:
                        # 分界线消息
                        cutoff_message = history[-1]
                        deleted = await channel.purge(before=cutoff_message)
                        if deleted:
                             print(f"姐姐我帮你在频道 {channel.name} 清理了 {len(deleted)} 条旧消息，只留下了最新的{limit}条。")
                except discord.Forbidden:
                    print(f"哎呀，姐姐我在频道 {channel.name} 没得权限删除消息呀。")
                except discord.HTTPException as e:
                    print(f"清理频道 {channel.name} 个辰光出错了呀: {e}")

    async def on_ready(self):
        """璐瑶已连接 Discord。"""
        proactive_status = "开启" if self.proactive_chat_enabled else "关闭"
        forward_status = "开启" if self.artwork_forwarding_enabled else "关闭"
        model_name = config.OPENAI_MODEL_NAME or "未配置"
        channel_scope = (
            f"限定 {len(config.ALLOWED_CHANNEL_IDS.split(','))} 个频道"
            if config.ALLOWED_CHANNEL_IDS else "全部频道"
        )

        print("════════════════════════════════════════")
        print(f"  璐瑶 · 已上线")
        print(f"  {self.user.name} ({self.user.id})")
        print("────────────────────────────────────────")
        print(f"  模型       {model_name}")
        print(f"  响应范围   {channel_scope}")
        print(f"  潜水插话   {proactive_status} · 概率 {self.proactive_chat_probability * 100:.0f}% · 冷却 {self.proactive_cooldown_seconds}s")
        print(f"  自动转图   {forward_status}")
        print("────────────────────────────────────────")
        print("  @璐瑶      有事直接说")
        print("  /imagine   文生图")
        print("  解析       图片反推提示词")
        print("────────────────────────────────────────")
        print("  管理员指令  赶紧睡吧 / 该起来了")
        print("              关闭自动转图 / 开启自动转图")
        print("              状态")
        print("════════════════════════════════════════")

    def _format_runtime_status(self) -> str:
        return (
            f"潜水插话={'开启' if self.proactive_chat_enabled else '关闭'}"
            f"({self.proactive_chat_probability * 100:.0f}%) · "
            f"自动转图={'开启' if self.artwork_forwarding_enabled else '关闭'}"
        )

    def _print_runtime_status(self):
        print(f"[璐瑶] 当前状态 | {self._format_runtime_status()}")

    def _log_switch_change(self, name: str, enabled: bool, operator: discord.abc.User):
        state = "开启" if enabled else "关闭"
        print(f"[璐瑶] 开关切换 | {name} → {state} | 操作者: {operator} ({operator.id})")
        self._print_runtime_status()

    async def _handle_artwork_message(self, message: discord.Message):
        """处理来自画图机器人的消息，无论是新建的还是编辑过的。"""
        # 如果是ID为 1444895127590928424 的机器人在指定频道发的画图结果
        if not (message.author.id == 1444895127590928424 and message.channel.id == 1444908373467332679):
            return

        print(f"检测到目标机器人[1444895127590928424]在目标频道[1444908373467332679]的消息活动 (ID: {message.id})。")
        # 只要消息里有嵌入式卡片，并且卡片里有图片和页脚
        if message.embeds and message.embeds[0].image and message.embeds[0].footer and message.embeds[0].footer.text:
            print("嵌入式卡片验证通过。")
            # 从 footer 解析出请求者
            footer_text = message.embeds[0].footer.text
            match = re.search(r"请求者:\s*([^|]+)", footer_text)
            if match:
                requester_name = match.group(1).strip()
                print(f"从图片信息中提取到请求者：'{requester_name}'")
                # 在服务器成员中找到这个人 (尝试匹配服务器昵称、用户名和全局名，忽略大小写)
                original_author = discord.utils.find(
                    lambda m: requester_name.lower() == m.name.lower() or
                              (m.global_name and requester_name.lower() == m.global_name.lower()) or
                              requester_name.lower() == m.display_name.lower(),
                    message.guild.members
                )
                
                if not original_author:
                    print(f"在服务器里找不到叫 '{requester_name}' 的人。")
                else:
                    print(f"成功找到用户: {original_author.name}")
                    image_url = message.embeds[0].image.url
                    filename = f"{uuid.uuid4()}.png"
                    image_path = os.path.join(TEMP_DIR, filename)
                    
                    print(f"准备下载图片: {image_url}")
                    if await download_image(image_url, image_path):
                        print("图片下载成功，准备转发...")
                        prompt_text = None
                        negative_prompt_text = None
                        if message.embeds[0].description:
                            description = message.embeds[0].description
                            # 分别提取正面和反向提示词
                            prompt_match = re.search(r"提示词:\s*(.*?)\s*反向提示词:", description, re.DOTALL)
                            if prompt_match:
                                prompt_text = prompt_match.group(1).strip()
                                print(f"成功提取到正面提示词。")
                            else:
                                print("未找到正面提示词。")
                            
                            negative_prompt_match = re.search(r"反向提示词:\s*(.*)", description, re.DOTALL)
                            if negative_prompt_match:
                                negative_prompt_text = negative_prompt_match.group(1).strip()
                                print(f"成功提取到反向提示词。")
                            else:
                                print("未找到反向提示词。")
                        
                        await self._forward_to_artwork_forum(
                            original_author, 
                            [discord.File(image_path)], 
                            prompt=prompt_text, 
                            negative_prompt=negative_prompt_text
                        )
                        await aiofiles.os.remove(image_path)
                    else:
                        print("图片下载失败。")
            else:
                print(f"无法从页脚 '{footer_text}' 中解析出请求者，忽略。")
        else:
            print("消息中的嵌入式卡片不完整（缺少图片或页脚信息），忽略。")

    async def on_message_edit(self, before: discord.Message, after: discord.Message):
        """当消息被编辑时..."""
        # 我们只关心机器人编辑的消息
        if not after.author.bot:
            return
        await self._handle_artwork_message(after)

    def _is_admin(self, author: discord.User | discord.Member) -> bool:
        user_id = str(author.id)
        if config.ADMIN_USER_ID and user_id == config.ADMIN_USER_ID:
            return True
        if config.TOMKK_USER_ID and user_id == config.TOMKK_USER_ID:
            return True
        return False

    def _strip_bot_mention(self, content: str) -> str:
        if not self.user:
            return (content or "").strip()
        return (
            (content or "")
            .replace(f"<@!{self.user.id}>", "")
            .replace(f"<@{self.user.id}>", "")
            .strip()
        )

    def _is_favor_query(self, message: discord.Message) -> bool:
        text = self._strip_bot_mention(message.content)
        return text.startswith("好感")

    def _favor_query_target(self, message: discord.Message) -> Optional[discord.User | discord.Member]:
        for member in message.mentions:
            if member.id != self.user.id:
                return member
        return None

    async def _handle_favor_query_command(self, message: discord.Message) -> bool:
        """管理员查询某人好感。返回 True 表示已处理。"""
        target_member = self._favor_query_target(message)
        if not target_member:
            await message.channel.send("格式：`好感 @某人`")
            return True

        state = data_manager.get_user_favor_state(str(target_member.id))
        favor = int(state.get("favor", 0))
        stage = self._favor_stage(favor)
        stage_label = self._favor_stage_label(stage)
        total_messages = int(state.get("total_messages", 0))
        last_message_at = state.get("last_message_at") or "无记录"
        events = state.get("events", []) or []
        last_event = events[-1] if events else None

        if last_event:
            delta = int(last_event.get("delta", 0))
            delta_text = f"{delta:+d}"
            reason = last_event.get("reason", "unknown")
            snippet = last_event.get("snippet", "")
            last_event_text = f"最近变动：{delta_text}（{reason}）\n片段：{snippet}"
        else:
            last_event_text = "最近变动：无"

        await message.channel.send(
            f"{target_member.mention} 的好感信息：\n"
            f"- 当前好感：{favor}/{FAVOR_MAX}\n"
            f"- 阶段：{stage_label}（{stage}）\n"
            f"- 累计记录轮数：{total_messages}\n"
            f"- 上次更新时间：{last_message_at}\n"
            f"- {last_event_text}"
        )
        print(
            f"[璐瑶] 好感查询 | 目标: {target_member} ({target_member.id}) "
            f"favor={favor} stage={stage} | 操作者: {message.author} ({message.author.id})"
        )
        return True

    async def on_message(self, message):
        """每次你说话、发图，我都会看到..."""
        # 0. 忽略机器人自己
        if message.author.bot:
            return

        # 1. 好感查询（管理员专用，优先于 @ 回复，避免被插话逻辑吞掉）
        if self._is_favor_query(message):
            if self._is_admin(message.author):
                await self._handle_favor_query_command(message)
            else:
                await message.channel.send("这个指令不对你开放。")
            return

        # 2. 优先处理@消息，确保任何情况下都能响应
        if self.user.mentioned_in(message):
            try:
                await self._handle_mention(message)
            except Exception as e:
                print(f"处理@消息时发生网络错误或其它异常: {e}")
            return # 处理完@后，直接结束，不再执行后续逻辑

        # --- 调试日志：打印所有收到的用户消息 ---
        channel_name = message.channel.name if hasattr(message.channel, 'name') else f"DM with {message.author}"
        print(f"[Debug] New message from {message.author} in channel #{channel_name} ({message.channel.id}): '{message.content}'")

        # --- 处理用户发的消息 ---
        # 3. 管理员指令检查：拥有最高优先权，不受频道限制
        if self._is_admin(message.author):
            if message.content == "赶紧睡吧":
                self.proactive_chat_enabled = False
                await data_manager.set_setting("proactive_chat_enabled", False)
                self._log_switch_change("潜水插话", False, message.author)
                await message.channel.send("知道了。我不插嘴了。")
                return
            elif message.content == "该起来了":
                self.proactive_chat_enabled = True
                await data_manager.set_setting("proactive_chat_enabled", True)
                self._log_switch_change("潜水插话", True, message.author)
                await message.channel.send("嗯，醒了。")
                return
            elif message.content in ["关闭自动转图", "待机"]:
                self.artwork_forwarding_enabled = False
                await data_manager.set_setting("artwork_forwarding_enabled", False)
                self._log_switch_change("自动转图", False, message.author)
                await message.channel.send("好，不转图了。")
                return
            elif message.content == "开启自动转图":
                self.artwork_forwarding_enabled = True
                await data_manager.set_setting("artwork_forwarding_enabled", True)
                self._log_switch_change("自动转图", True, message.author)
                await message.channel.send("转图开了。")
                return
            elif message.content == "状态":
                status_text = self._format_runtime_status()
                print(f"[璐瑶] 状态查询 | {status_text} | 操作者: {message.author} ({message.author.id})")
                await message.channel.send(f"当前：{status_text}")
                return
            elif message.content.startswith("!reload"):
                parts = message.content.split()
                if len(parts) < 2:
                    await message.channel.send("重载哪个模块？例如 `!reload drawing`。")
                    return
                
                cog_name = parts[1]
                try:
                    await self.reload_extension(f"bot.{cog_name}")
                    await message.channel.send(f"`{cog_name}` 已重载。")
                    print(f"Cog 'bot.{cog_name}' reloaded successfully by admin.")
                except commands.ExtensionNotFound:
                    await message.channel.send(f"找不到 `{cog_name}` 这个模块。")
                except Exception as e:
                    await message.channel.send(f"重载模块 `{cog_name}` 的时候出错了呀：\n```py\n{e}\n```")
                    print(f"Error reloading cog 'bot.{cog_name}': {e}")
                return
        
        # 4. 核心指令检查
        if message.content.strip().lower() == "解析":
            await self._handle_reverse_prompt_command(message)
            return

        # 5. 检查频道是否在允许列表中，如果设置了该规则，则不符合的频道直接忽略后续所有逻辑
        if config.ALLOWED_CHANNEL_IDS:
            allowed_ids = [int(cid.strip()) for cid in config.ALLOWED_CHANNEL_IDS.split(',')]
            if message.channel.id not in allowed_ids:
                print(f"[Debug] Message in channel {message.channel.id} ignored due to ALLOWED_CHANNEL_IDS setting.")
                return # 不在允许的频道，直接返回

        # 6. 特定频道图片删除与转发
        if self.artwork_forwarding_enabled and message.channel.id in [1442454462730993697, 1442459566565752845]:
            if message.attachments and any(att.content_type and att.content_type.startswith('image/') for att in message.attachments):
                try:
                    original_author = message.author
                    channel = message.channel
                    
                    image_files = [await att.to_file() for att in message.attachments if att.content_type and att.content_type.startswith('image/')]
                    await self._forward_to_artwork_forum(original_author, image_files)

                    await message.delete()
                    await channel.send(f"{original_author.mention} 这里是聊天频道，发图去作品分享区。")

                    # 护短：不删小哈的回复
                except discord.Forbidden:
                    print(f"哎呀，姐姐我在频道 {message.channel.name} 没得权限删除消息呀。")
                except discord.HTTPException as e:
                    print(f"删除图片消息个辰光出错了呀: {e}")
                return
        
        # 7. 其他指令和互动
        if message.content in ["赶紧睡吧", "该起来了", "关闭自动转图", "开启自动转图", "状态", "待机"] and not self._is_admin(message.author):
            print(f"[璐瑶] 开关操作被拒绝 | {message.author} ({message.author.id}) 尝试: {message.content}")
            await message.channel.send("我只听白衣胜雪的。")
            return

        if not self.proactive_chat_enabled:
            return

        await self._maybe_trigger_proactive_chat(message)

    def _get_channel_lock(self, channel_id: int) -> asyncio.Lock:
        if channel_id not in self._channel_locks:
            self._channel_locks[channel_id] = asyncio.Lock()
        return self._channel_locks[channel_id]

    def _is_proactive_on_cooldown(self, channel_id: int) -> bool:
        last_at = self._last_proactive_at.get(channel_id)
        if not last_at:
            return False
        elapsed = (datetime.now(timezone.utc) - last_at).total_seconds()
        return elapsed < self.proactive_cooldown_seconds

    async def _maybe_trigger_proactive_chat(self, message: discord.Message):
        channel_id = message.channel.id

        if self._is_proactive_on_cooldown(channel_id):
            print(f"[Proactive] 跳过：频道冷却中 (channel={channel_id})")
            return

        lock = self._get_channel_lock(channel_id)
        if lock.locked():
            print(f"[Proactive] 跳过：本频道正在生成回复 (channel={channel_id})")
            return

        history = [msg async for msg in message.channel.history(limit=2)]
        if len(history) > 1 and history[1].author == self.user:
            print(f"[Proactive] 跳过：上一条是璐瑶自己发的 (channel={channel_id})")
            return

        roll = random.random()
        if roll >= self.proactive_chat_probability:
            return

        print(
            f"[Proactive] 触发插话 roll={roll:.3f}, threshold={self.proactive_chat_probability} "
            f"(channel={channel_id}, author={message.author})"
        )

        async with lock:
            if self._is_proactive_on_cooldown(channel_id):
                print(f"[Proactive] 跳过：频道冷却中（锁内复检） (channel={channel_id})")
                return

            history = [msg async for msg in message.channel.history(limit=2)]
            if len(history) > 1 and history[1].author == self.user:
                print(f"[Proactive] 跳过：上一条是璐瑶自己发的（锁内复检） (channel={channel_id})")
                return

            try:
                sent = await self._handle_proactive_chat(message)
                if sent:
                    self._last_proactive_at[channel_id] = datetime.now(timezone.utc)
            except Exception as e:
                print(f"[Proactive] 插话处理失败: {e}")

    async def _get_image_from_message(self, message) -> Optional[str]: # 修改这一行
        """看看消息里厢有没得啥好看个图呀"""
        if message.attachments:
            attachment = message.attachments[0]
            if attachment.content_type and attachment.content_type.startswith('image/'):
                filename = f"{uuid.uuid4()}.jpg"
                image_path = os.path.join(TEMP_DIR, filename)
                await attachment.save(image_path)
                return image_path

        for word in message.content.split():
            if word.startswith('http') and any(ext in word for ext in ['.png', '.jpg', '.jpeg', '.webp']):
                filename = f"{uuid.uuid4()}.jpg"
                path = os.path.join(TEMP_DIR, filename)
                if await download_image(word, path):
                    return path
        return None

    def _is_tomkk(self, author: discord.User | discord.Member) -> bool:
        if config.TOMKK_USER_ID and str(author.id) == config.TOMKK_USER_ID:
            return True
        names = [author.name, getattr(author, "global_name", None), getattr(author, "display_name", None)]
        return any(n and "tomkk" in n.lower() for n in names)

    def _is_xiaoha(self, author: discord.User | discord.Member) -> bool:
        if config.XIAOHA_USER_ID and str(author.id) == config.XIAOHA_USER_ID:
            return True
        names = [author.name, getattr(author, "global_name", None), getattr(author, "display_name", None)]
        return any(n and ("小哈" in n or "xiaoha" in n.lower()) for n in names)

    def _format_context_line(self, msg: discord.Message) -> str:
        content = msg.content or "(无文字)"
        if self._is_xiaoha(msg.author):
            return f"小哈 [你的狗]: {content}"
        if msg.author == self.user:
            return f"璐瑶: {content}"
        return f"{msg.author.display_name}: {content}"

    async def _build_channel_context(
        self, message: discord.Message, limit: int = 10
    ) -> tuple[str, Literal["none", "stale", "active", "from_xiaoha"]]:
        history = [msg async for msg in message.channel.history(limit=limit)]
        history.reverse()
        context_str = "\n".join(self._format_context_line(msg) for msg in history)
        situation = self._xiaoha_situation(history, message)
        return context_str, situation

    def _xiaoha_situation(
        self, history: list[discord.Message], trigger: discord.Message
    ) -> Literal["none", "stale", "active", "from_xiaoha"]:
        if self._is_xiaoha(trigger.author):
            return "from_xiaoha"

        latest_xiaoha: Optional[discord.Message] = None
        for msg in history:
            if msg.id == trigger.id:
                continue
            if self._is_xiaoha(msg.author):
                latest_xiaoha = msg

        if not latest_xiaoha:
            return "none"

        age = (trigger.created_at - latest_xiaoha.created_at).total_seconds()
        if age <= 120:
            return "active"
        return "stale"

    def _format_trigger_focus(self, message: discord.Message) -> str:
        line = self._format_context_line(message)
        if message.attachments and any(
            att.content_type and att.content_type.startswith("image/") for att in message.attachments
        ):
            line += " [含图片]"
        return f"【当前要接的话】{line}"

    def _xiaoha_context_instruction(self, situation: Literal["none", "stale", "active", "from_xiaoha"]) -> str:
        if situation == "none":
            return ""
        if situation == "stale":
            return (
                " 聊天记录里较早出现过小哈的话，但与当前话题无关。不要翻旧账训斥它，"
                "优先回应【当前要接的话】里人类正在讨论的内容。"
            )
        if situation == "active":
            return (
                " 小哈刚刚在说话。若它在捣乱、没礼貌、胡说或乱比喻喧宾夺主，可淡淡训斥，直呼「小哈」。"
                "若它只说一句正常的话、或技术内容没错，不要骂它「话太多」。"
                "即便如此，也要先接住【当前要接的话】的话题，不要答非所问。"
            )
        return (
            " 当前触发消息来自小哈。像主人管狗一样回应它：调皮就训斥，叫「小哈」；"
            "说得还行就淡淡带过。不要对一句正常短话硬说「话太多」。"
        )

    def _audience_prompt(self, author: discord.User | discord.Member) -> str:
        if self._is_tomkk(author):
            return " 对方是 Tomkk，是你唯一亲近的人。对他你可以依然冷艳，但要明显多一点亲密和热情——这是你只对他才有的另一面，不要对其他人这样。"
        return ""

    def _clamp_favor(self, favor: int) -> int:
        return max(0, min(FAVOR_MAX, int(favor)))

    def _favor_stage(self, favor: int) -> str:
        favor = self._clamp_favor(favor)
        if favor >= 100:
            return "bond"
        if favor >= 60:
            return "warm"
        if favor >= 30:
            return "familiar"
        if favor >= 10:
            return "normal"
        return "cold"

    def _favor_stage_label(self, stage: str) -> str:
        labels = {
            "cold": "初识",
            "normal": "普通",
            "familiar": "熟悉",
            "warm": "亲近",
            "bond": "默契",
        }
        return labels.get(stage, stage)

    def _favor_tone_prompt(self, favor: int) -> str:
        favor = self._clamp_favor(favor)
        stage = self._favor_stage(favor)
        label = self._favor_stage_label(stage)
        examples = {
            "cold": "「说重点。」「嗯。」「图发来。」",
            "normal": "「可以，继续说。」「参数贴出来。」「这倒有点意思。」",
            "familiar": "「上次那张比这张干净。」「行，按我说的改。」「……你又熬夜了？」",
            "warm": "「发来看看，我帮你盯一眼。」「别急，报错全文贴来。」「嗯，这次比上回好多了。」",
            "bond": "「在。说吧。」「……算了，陪你说两句。」「你这点我记着呢，不用重复。」",
        }
        tone_rules = {
            "cold": "保持偏冷、短句、对题。礼貌在，热情不在。",
            "normal": "保持冷静礼貌，可比初识多给一点解释，但仍保持距离。",
            "familiar": "语气比默认稍松，可自然接话与简短追问，别过度热情。",
            "warm": "语气明显更柔和，愿意多说半句，允许自然关心，但不撒娇不肉麻。",
            "bond": "像很熟的熟人，语气随意自然，可主动接住对方情绪，但仍不肉麻、不对路人复制 Tomkk 式亲密。",
        }
        return (
            f" 当前与该用户好感度={favor}/{FAVOR_MAX}（{label}）。"
            f"{tone_rules[stage]}"
            f"参考语气示例（勿照抄，按场景变通）：{examples[stage]}"
        )

    def _build_persona_with_favor(self, favor: int) -> str:
        return self.persona + "\n\n【好感系统约束】" + self._favor_tone_prompt(favor)

    def _parse_favor_event_time(self, value: Optional[str]) -> Optional[datetime]:
        if not value:
            return None
        try:
            return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError:
            return None

    def _favor_positive_gain_today(self, events: list) -> int:
        today = datetime.now(timezone.utc).date()
        total = 0
        for event in events:
            delta = int(event.get("delta", 0) or 0)
            if delta <= 0:
                continue
            at = self._parse_favor_event_time(event.get("at"))
            if at and at.astimezone(timezone.utc).date() == today:
                total += delta
        return total

    def _favor_last_positive_at(self, events: list) -> Optional[datetime]:
        for event in reversed(events):
            if int(event.get("delta", 0) or 0) > 0:
                return self._parse_favor_event_time(event.get("at"))
        return None

    def _favor_tag_on_cooldown(self, events: list, tag: str, now: datetime) -> bool:
        cooldown = FAVOR_EVENT_COOLDOWN_SECONDS.get(tag, 0)
        if cooldown <= 0:
            return False
        for event in reversed(events):
            reasons = str(event.get("reason", "")).split(",")
            if tag not in reasons:
                continue
            if int(event.get("delta", 0) or 0) <= 0:
                continue
            at = self._parse_favor_event_time(event.get("at"))
            if not at:
                continue
            if (now - at.astimezone(timezone.utc)).total_seconds() < cooldown:
                return True
            break
        return False

    def _compute_favor_delta(
        self,
        text: str,
        has_image: bool,
        is_tomkk: bool,
        events: Optional[list] = None,
    ) -> tuple[int, str]:
        content = (text or "").strip().lower()
        if not content and not has_image:
            return 0, "empty_ping"

        insult_hit = any(k in content for k in ["傻", "滚", "废物", "垃圾", "你配", "脑残", "弱智", "去死"])
        rude_hit = any(k in content for k in ["闭嘴", "少废话", "别装", "装什么", "阴阳怪气"])
        thanks_hit = any(k in content for k in ["谢谢", "感谢", "辛苦", "多谢", "thx", "thanks"])
        polite_hit = any(k in content for k in ["请", "麻烦", "可以吗", "劳驾", "拜托"])
        constructive_hit = any(k in content for k in ["参数", "报错", "节点", "工作流", "怎么", "如何", "帮我看", "建议"])

        tag_deltas: list[tuple[str, int]] = []
        if insult_hit:
            tag_deltas.append(("insult", -10))
        if rude_hit:
            tag_deltas.append(("rude", -4))
        if thanks_hit:
            tag_deltas.append(("thanks", 3))
        if polite_hit:
            tag_deltas.append(("polite", 2))
        if constructive_hit:
            tag_deltas.append(("constructive", 1))
        if has_image and not insult_hit:
            tag_deltas.append(("shared_image", 1))

        if is_tomkk and any(delta < 0 for _, delta in tag_deltas):
            tag_deltas = [
                (tag, int(delta / 2) if delta < 0 else delta)
                for tag, delta in tag_deltas
            ]
            tag_deltas.append(("tomkk_soften_penalty", 0))

        negative_delta = sum(delta for _, delta in tag_deltas if delta < 0)
        positive_tags = [(tag, delta) for tag, delta in tag_deltas if delta > 0]

        if not positive_tags:
            delta = max(-12, min(8, negative_delta))
            reasons = [tag for tag, value in tag_deltas if value != 0 or tag == "tomkk_soften_penalty"]
            return delta, ",".join(reasons) if reasons else "neutral"

        now = datetime.now(timezone.utc)
        event_history = list(events or [])
        blocked_tags: list[str] = []
        applied_positive: list[tuple[str, int]] = []

        last_positive_at = self._favor_last_positive_at(event_history)
        if last_positive_at and (now - last_positive_at).total_seconds() < FAVOR_POSITIVE_MIN_INTERVAL:
            blocked_tags.append("spam_interval")
        else:
            for tag, value in positive_tags:
                if self._favor_tag_on_cooldown(event_history, tag, now):
                    blocked_tags.append(f"cooldown:{tag}")
                    continue
                applied_positive.append((tag, value))

        positive_delta = sum(value for _, value in applied_positive)
        if positive_delta > 0:
            gained_today = self._favor_positive_gain_today(event_history)
            remaining = FAVOR_DAILY_GAIN_CAP - gained_today
            if remaining <= 0:
                positive_delta = 0
                blocked_tags.append("daily_cap")
            elif positive_delta > remaining:
                positive_delta = remaining
                blocked_tags.append("daily_trim")

        delta = negative_delta + positive_delta
        delta = max(-12, min(8, delta))

        reasons = [tag for tag, value in tag_deltas if value < 0]
        reasons.extend(tag for tag, _ in applied_positive)
        if is_tomkk and "tomkk_soften_penalty" not in reasons and any(
            tag in ("insult", "rude") for tag, value in tag_deltas if value < 0
        ):
            reasons.append("tomkk_soften_penalty")
        if blocked_tags:
            reasons.extend(blocked_tags)
        if not reasons:
            reasons = ["neutral"]
        return delta, ",".join(reasons)

    def _image_reply_hint(self) -> str:
        return (
            " 图片里若有报错、节点、参数或工作流界面，看清后给具体指点；"
            "画作就谈画面本身。不要空话敷衍。"
        )

    def _speaking_guard(self) -> str:
        return (
            " 说话铁律：对题、短、有内容。"
            "禁止空泛玄学、心态升华、人生导师口吻，禁止「问题不在……在你看待……」「你急什么」「它已经告诉你了」「看着办」这类空话。"
            "闲聊就接闲聊，技术就谈可操作的判断或问缺什么信息。冷艳靠语气短净，不靠装深沉。"
        )

    def _build_proactive_prompt(
        self,
        context_str: str,
        trigger_focus: str,
        audience: str,
        has_image: bool,
        xiaoha_situation: Literal["none", "stale", "active", "from_xiaoha"],
    ) -> str:
        """插话专用 prompt：代码已按概率触发，此处只要求生成一句接话。"""
        scene = "看到了大家的聊天记录和一张图片" if has_image else "看到了大家的聊天记录"
        xiaoha_hint = self._xiaoha_context_instruction(xiaoha_situation)
        image_hint = self._image_reply_hint() if has_image else ""
        speaking_guard = self._speaking_guard()
        return (
            f"你是璐瑶，正在群里潜水，{scene}：\n\n---\n{context_str}\n---\n\n"
            f"{trigger_focus}\n"
            "按人设接一句话。必须紧扣【当前要接的话】，不要答非所问。"
            "若有人贬低小哈，护短。只输出一条消息，不要超过三行。"
            f"{speaking_guard}{image_hint}{xiaoha_hint}"
            "直接说出要发的那句话，不要解释。\n"
            f"{audience}"
        )

    def _build_mention_prompt(
        self,
        user_prompt: str,
        context_str: str,
        trigger_focus: str,
        audience: str,
        has_image: bool,
        xiaoha_situation: Literal["none", "stale", "active", "from_xiaoha"],
    ) -> str:
        xiaoha_hint = self._xiaoha_context_instruction(xiaoha_situation)
        image_hint = self._image_reply_hint() if has_image else ""
        speaking_guard = self._speaking_guard()
        context_block = f"\n\n以下是频道最近的聊天记录：\n---\n{context_str}\n---\n" if context_str else ""
        if has_image:
            return (
                f"用户@了你（璐瑶），说了「{user_prompt}」，还发了张图。{context_block}\n"
                f"{trigger_focus}\n"
                "按人设回应。紧扣对方的话和【当前要接的话】，不要答非所问。"
                f"{speaking_guard}{image_hint}{xiaoha_hint}{audience}直接说出要发的那句话。"
            )
        return (
            f"用户@了你（璐瑶），说了：「{user_prompt}」。{context_block}\n"
            f"{trigger_focus}\n"
            "按人设回应。紧扣对方的话和【当前要接的话】，不要答非所问。"
            f"{speaking_guard}{xiaoha_hint}{audience}直接说出要发的那句话。"
        )

    async def _handle_proactive_chat(self, message) -> bool:
        """姐姐我自家想插句嘴了呀"""
        async with message.channel.typing():
            context_str, xiaoha_situation = await self._build_channel_context(message)
            trigger_focus = self._format_trigger_focus(message)
            image_path = await self._get_image_from_message(message)
            audience = self._audience_prompt(message.author)
            prompt = self._build_proactive_prompt(
                context_str, trigger_focus, audience, bool(image_path), xiaoha_situation
            )

            if image_path:
                response = await get_chat_completion_with_image(prompt, self.persona, image_path)
                await aiofiles.os.remove(image_path)
            else:
                response = await get_chat_completion(prompt, self.persona)

            if not response:
                print("[Proactive] 模型返回空，用兜底短句重试一次")
                retry_prompt = prompt + "\n\n你必须输出一句可发送的中文短句，不要留空。"
                response = await get_chat_completion(retry_prompt, self.persona)

            if response:
                await message.channel.send(response)
                print(f"[Proactive] 已发送: {response[:50]}...")
                return True
            print("[Proactive] 重试后仍为空，放弃本次插话")
            return False

    async def _handle_reverse_prompt_command(self, message):
        """处理反推指令"""
        print(f"收到来自 {message.author} 的 '解析' 指令。")
        image_path = None
        
        # 检查回复的消息中是否有图片
        if message.reference and message.reference.resolved:
            ref_message = message.reference.resolved
            print(f"指令是回复消息 {ref_message.id}，正在检查该消息中的图片...")
            if ref_message.attachments and ref_message.attachments[0].content_type.startswith('image/'):
                 image_path = await self._get_image_from_message(ref_message)
                 if image_path:
                    print(f"从回复的消息中成功提取图片: {image_path}")
        
        # 如果回复中没有，检查当前消息的附件
        if not image_path and message.attachments and message.attachments[0].content_type.startswith('image/'):
            print("正在检查当前消息附件中的图片...")
            image_path = await self._get_image_from_message(message)
            if image_path:
                print(f"从当前消息附件中成功提取图片: {image_path}")

        if not image_path:
            print("未找到可供解析的图片。")
            await message.channel.send("图呢。")
            return

        async with message.channel.typing():
            await message.channel.send("等着。")
            
            try:
                print(f"开始调用 ComfyUI 对图片 {image_path} 进行反推...")
                tags = await get_image_tags_from_comfyui(image_path)
                print(f"ComfyUI 返回结果: {tags[:200]}...") # 只打印前200个字符以防过长
                
                # 将结果分段发送，避免超过 Discord 2000 字符限制
                if len(tags) > 1900:
                    await message.channel.send("内容太长，分两条发。")
                    split_point = tags.rfind(',', 0, 1900)
                    if split_point == -1: split_point = 1900
                    
                    part1 = tags[:split_point]
                    part2 = tags[split_point:]
                    
                    await message.channel.send(f"```{part1}```")
                    await message.channel.send(f"```{part2}```")
                else:
                    await message.channel.send(f"```{tags}```")
                print("已成功将解析结果发送到 Discord。")

            except Exception as e:
                print(f"处理 '解析' 指令时发生严重错误: {e}")
                await message.channel.send("解析失败了。再试一次。")
            finally:
                if image_path:
                    print(f"正在删除临时图片文件: {image_path}")
                    await aiofiles.os.remove(image_path)

    async def _handle_mention(self, message):
        """处理@我个消息"""
        user_prompt = message.content.replace(f'<@!{self.user.id}>', '').replace(f'<@{self.user.id}>', '').strip()
        user_id = str(message.author.id)
        favor_state = data_manager.get_user_favor_state(user_id)
        current_favor = self._clamp_favor(int(favor_state.get("favor", 0)))
        persona_with_favor = self._build_persona_with_favor(current_favor)

        async with self._get_channel_lock(message.channel.id):
            async with message.channel.typing():
                context_str, xiaoha_situation = await self._build_channel_context(message)
                trigger_focus = self._format_trigger_focus(message)
                image_path = await self._get_image_from_message(message)
                audience = self._audience_prompt(message.author) + self._favor_tone_prompt(current_favor)
                
                if image_path:
                    full_prompt = self._build_mention_prompt(
                        user_prompt or "(无文字，只发了图)",
                        context_str,
                        trigger_focus,
                        audience,
                        has_image=True,
                        xiaoha_situation=xiaoha_situation,
                    )
                    response = await get_chat_completion_with_image(full_prompt, persona_with_favor, image_path)
                    await aiofiles.os.remove(image_path)
                else:
                    if not user_prompt:
                        if xiaoha_situation in ("active", "from_xiaoha"):
                            user_prompt = "（对方@了你但没说什么，小哈刚才在说话）"
                        elif self._is_tomkk(message.author):
                            await message.channel.send("嗯？怎么了。")
                            return
                        else:
                            await message.channel.send("有事就说，别光看着。")
                            return
                    full_prompt = self._build_mention_prompt(
                        user_prompt,
                        context_str,
                        trigger_focus,
                        audience,
                        has_image=False,
                        xiaoha_situation=xiaoha_situation,
                    )
                    response = await get_chat_completion(full_prompt, persona_with_favor)
                
                if response:
                    await message.channel.send(response)
                    delta, reason = self._compute_favor_delta(
                        user_prompt,
                        bool(image_path),
                        self._is_tomkk(message.author),
                        favor_state.get("events", []),
                    )
                    favor_after = self._clamp_favor(current_favor + delta)
                    await data_manager.apply_favor_delta(
                        user_id=user_id,
                        delta=delta,
                        reason=reason,
                        message_snippet=(user_prompt or "(无文字，只发了图)"),
                        stage=self._favor_stage(favor_after),
                    )

    def run_bot(self):
        """启动璐瑶 bot。"""
        if config.DISCORD_TOKEN:
            if not all([config.OPENAI_API_BASE, config.OPENAI_API_KEY, config.OPENAI_MODEL_NAME]):
                print("[璐瑶] 警告：OpenAI 配置不完整，对话功能可能不可用。")
            
            retries = 0
            max_retries = 5
            while retries < max_retries:
                try:
                    print(f"[璐瑶] 正在连接 Discord... (第 {retries + 1} 次)")
                    super().run(config.DISCORD_TOKEN)
                except discord.LoginFailure:
                    print("[璐瑶] 登录失败，请检查 DISCORD_TOKEN。")
                    break
                except Exception as e:
                    print(f"[璐瑶] 启动异常: {e}")
                    retries += 1
                    if retries < max_retries:
                        wait_time = min(2 ** retries, 60)
                        print(f"[璐瑶] {wait_time} 秒后重试...")
                        import time
                        time.sleep(wait_time)
                    else:
                        print("[璐瑶] 已达最大重试次数，启动失败。")
            if retries == max_retries:
                print("[璐瑶] 机器人启动失败。")
        else:
            print("[璐瑶] 未找到 DISCORD_TOKEN，请在 .env 中配置。")
