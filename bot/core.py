import discord
from discord.ext import commands, tasks
from datetime import datetime, timedelta, timezone
from settings import config
from ai.client import get_chat_completion, get_chat_completion_with_image, download_image, get_image_tags_from_comfyui
from bot.data_manager import data_manager
from urllib.parse import urlparse
import os
import uuid
import shlex
import random
import aiofiles.os
import asyncio
import re
from typing import Optional # 添加这一行

TEMP_DIR = "temp"

class SassySisterBot(commands.Bot):
    def __init__(self, **options):
        # --- 代理设置 ---
        proxy_url = options.pop('proxy', None)
        if proxy_url:
            print(f"姐姐我看到侬个代理了哦: {proxy_url}")

        # --- 机器人意图跟初始化 ---
        intents = discord.Intents.default()
        intents.message_content = True
        intents.members = True  # 开启成员意图，为了迎接新人呀
        
        # 直接把代理 URL 交给 discord.py 来处理
        super().__init__(command_prefix="!", intents=intents, proxy=proxy_url, **options)

        # --- 其他个东西 ---
        self.persona = self._load_persona()
        self._ensure_temp_dir()
        self.proactive_chat_enabled = data_manager.get_setting("proactive_chat_enabled", True)
        self.proactive_chat_probability = config.PROACTIVE_CHAT_PROBABILITY
        self.artwork_forwarding_enabled = data_manager.get_setting("artwork_forwarding_enabled", True)
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
            return "你是璐瑶，一个来历不明、冷艳知性的女子。话不多，但每句都有分量；高雅，偶尔睥睨，但不拒人千里。小哈是你的宠物狗，你对它很护短。Tomkk是你唯一亲近的人，只对他才会多一分亲密和热情。"

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
        print(f"  潜水插话   {proactive_status} · 概率 {self.proactive_chat_probability * 100:.0f}%")
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

    def _generate_welcome_message(self, member: discord.Member) -> str:
        """生成欢迎新成员的介绍信息。"""
        return f"""{member.mention}，进来了。

---

**👨‍🎨 画师：白衣胜雪**
画画频道里用 `/绘图`；`/设置`、`/workflow` 调风格。每次消耗「画卷」。

---

**🐶 小哈**
我的狗。灵感不够的时候，找它。
- 回复一张图 + `反推`
- 说 `画 <想法>`，它帮你凑提示词
- `@小哈` 也能聊

---

有事 @我。"""

    async def on_member_join(self, member):
        """当有新的小可爱加入我们的“画室”时……"""
        if config.WELCOME_CHANNEL_IDS:
            channel_ids = [int(cid.strip()) for cid in config.WELCOME_CHANNEL_IDS.split(',')]
            for channel_id in channel_ids:
                channel = self.get_channel(channel_id)
                if channel:
                    welcome_message = self._generate_welcome_message(member)
                    await channel.send(welcome_message)

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

    async def on_message(self, message):
        """每次你说话、发图，我都会看到..."""
        # 0. 忽略机器人自己
        if message.author.bot:
            return

        # 1. 优先处理@消息，确保任何情况下都能响应
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
        # 2. 管理员指令检查：拥有最高优先权，不受频道限制
        if config.ADMIN_USER_ID and str(message.author.id) == config.ADMIN_USER_ID:
            if message.content.startswith("!发送介绍"):
                # 优先选择被@的第一个人，如果没有，就选择发消息的管理员自己
                target_member = message.mentions[0] if message.mentions else message.author
                welcome_message = self._generate_welcome_message(target_member)
                await message.channel.send(welcome_message)
                try:
                    await message.delete() # 删除指令消息，保持频道整洁
                except discord.Forbidden:
                    print(f"没权限删除指令消息: {message.id}")
                return
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
        
        # 2. 核心指令检查
        if message.content.strip().lower() == "解析":
            await self._handle_reverse_prompt_command(message)
            return

        # 3. 检查频道是否在允许列表中，如果设置了该规则，则不符合的频道直接忽略后续所有逻辑
        if config.ALLOWED_CHANNEL_IDS:
            allowed_ids = [int(cid.strip()) for cid in config.ALLOWED_CHANNEL_IDS.split(',')]
            if message.channel.id not in allowed_ids:
                print(f"[Debug] Message in channel {message.channel.id} ignored due to ALLOWED_CHANNEL_IDS setting.")
                return # 不在允许的频道，直接返回

        # 4. 特定频道图片删除与转发
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
        
        # 5. 其他指令和互动
        if message.content in ["赶紧睡吧", "该起来了", "关闭自动转图", "开启自动转图", "状态", "待机"] and (not config.ADMIN_USER_ID or str(message.author.id) != config.ADMIN_USER_ID):
            print(f"[璐瑶] 开关操作被拒绝 | {message.author} ({message.author.id}) 尝试: {message.content}")
            await message.channel.send("我只听白衣胜雪的。")
            return

        if not self.proactive_chat_enabled:
            return

        history = [msg async for msg in message.channel.history(limit=2)]
        if len(history) > 1 and history[1].author == self.user:
            print(f"[Proactive] 跳过：上一条是璐瑶自己发的 (channel={message.channel.id})")
            return

        roll = random.random()
        if roll < self.proactive_chat_probability:
            print(f"[Proactive] 触发插话 roll={roll:.3f}, threshold={self.proactive_chat_probability} (channel={message.channel.id}, author={message.author})")
            try:
                await self._handle_proactive_chat(message)
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

    async def _build_channel_context(self, message: discord.Message, limit: int = 10) -> tuple[str, bool]:
        history = [msg async for msg in message.channel.history(limit=limit)]
        history.reverse()
        has_xiaoha = any(self._is_xiaoha(msg.author) for msg in history)
        context_str = "\n".join(self._format_context_line(msg) for msg in history)
        return context_str, has_xiaoha

    def _xiaoha_context_instruction(self, has_xiaoha: bool) -> str:
        if not has_xiaoha:
            return ""
        return (
            " 上下文中出现了小哈（你的狗）的发言。不要视而不见——像真的在养狗的主人那样有所反应。"
            "小哈在捣乱、没礼貌、胡说或调皮时，训斥它，必须直呼「小哈」，教它要有礼貌。"
            "小哈说得还行时可以淡淡带过或接一句；有人在骂小哈、欺负它时要护短。"
            "训斥或叫它时务必写出「小哈」这个名字。"
        )

    def _audience_prompt(self, author: discord.User | discord.Member) -> str:
        if self._is_tomkk(author):
            return " 对方是 Tomkk，是你唯一亲近的人。对他你可以依然冷艳，但要明显多一点亲密和热情——这是你只对他才有的另一面，不要对其他人这样。"
        return ""

    def _build_proactive_prompt(self, context_str: str, audience: str, has_image: bool, has_xiaoha: bool) -> str:
        """插话专用 prompt：代码已按概率触发，此处只要求生成一句接话。"""
        scene = "看到了大家的聊天记录和一张图片" if has_image else "看到了大家的聊天记录"
        xiaoha_hint = self._xiaoha_context_instruction(has_xiaoha)
        return (
            f"你（璐瑶）正在群里潜水，{scene}：\n\n---\n{context_str}\n---\n\n"
            "接一句话。简短、知性、高雅，能接茬，让人想继续聊。冷，但不拒人千里；"
            "偶尔睥睨，偶尔点破；若有人贬低小哈，要护短。不要超过三行。"
            f"{xiaoha_hint}"
            "必须输出一句可发送的中文短句。\n"
            f"{audience}直接说出你的回复，不要有任何多余的解释。"
        )

    def _build_mention_prompt(
        self,
        user_prompt: str,
        context_str: str,
        audience: str,
        has_image: bool,
        has_xiaoha: bool,
    ) -> str:
        xiaoha_hint = self._xiaoha_context_instruction(has_xiaoha)
        context_block = f"\n\n以下是频道最近的聊天记录：\n---\n{context_str}\n---\n" if context_str else ""
        if has_image:
            return (
                f"一个用户@了你（璐瑶），说了「{user_prompt}」，还发了张图。{context_block}\n"
                "请你根据人设，像真人一样用简短、知性、高雅的方式回应。话不多，从画面或对方意图切入，"
                f"冷而不冰，偶尔睥睨；若涉及小哈被贬低，要护短。{xiaoha_hint}{audience}直接说出你的回复。"
            )
        return (
            f"一个用户@了你（璐瑶），对你说了：「{user_prompt}」。{context_block}\n"
            "请你根据人设，像真人一样用简短、知性、高雅的方式回应。话不多，但要能接茬。"
            "冷，但不拒人千里；看穿对方在掩饰什么，偶尔点破；若涉及小哈被贬低，要护短。"
            f"{xiaoha_hint}{audience}直接说出你的回复。"
        )

    async def _handle_proactive_chat(self, message):
        """姐姐我自家想插句嘴了呀"""
        async with message.channel.typing():
            context_str, has_xiaoha = await self._build_channel_context(message)
            image_path = await self._get_image_from_message(message)
            audience = self._audience_prompt(message.author)
            prompt = self._build_proactive_prompt(context_str, audience, bool(image_path), has_xiaoha)

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
            else:
                print("[Proactive] 重试后仍为空，放弃本次插话")

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
        
        async with message.channel.typing():
            context_str, has_xiaoha = await self._build_channel_context(message)
            image_path = await self._get_image_from_message(message)
            audience = self._audience_prompt(message.author)
            
            if image_path:
                full_prompt = self._build_mention_prompt(
                    user_prompt or "(无文字，只发了图)",
                    context_str,
                    audience,
                    has_image=True,
                    has_xiaoha=has_xiaoha,
                )
                response = await get_chat_completion_with_image(full_prompt, self.persona, image_path)
                await aiofiles.os.remove(image_path)
            else:
                if not user_prompt:
                    if has_xiaoha:
                        user_prompt = "（对方@了你但没说什么，上下文里有小哈的发言）"
                    elif self._is_tomkk(message.author):
                        await message.channel.send("嗯？怎么了。")
                        return
                    else:
                        await message.channel.send("有事就说，别光看着。")
                        return
                full_prompt = self._build_mention_prompt(
                    user_prompt,
                    context_str,
                    audience,
                    has_image=False,
                    has_xiaoha=has_xiaoha,
                )
                response = await get_chat_completion(full_prompt, self.persona)
            
            if response:
                await message.channel.send(response)

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
