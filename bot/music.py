import discord
from discord import app_commands
from discord.ext import commands
import yt_dlp
import asyncio
from typing import List, Dict
import sys

# --- 配置 ---
YDL_OPTIONS = {
    'format': 'bestaudio[ext=m4a]/bestaudio/best',
    'noplaylist': True,
    'quiet': True,
    'no_warnings': True,
    'cookiefile': 'cookies.txt',  # 使用Cookie文件来避免YouTube的机器人验证
    # 'proxy': 'http://127.0.0.1:18888',  # 如果需要代理，可启用
    'geo_bypass': True,
    'user-agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/130.0.0.0 Safari/537.36',
    'playlistend': 10,  # 限制搜索结果数量
}

FFMPEG_OPTIONS = {
    'before_options': '-reconnect 1 -reconnect_streamed 1 -reconnect_delay_max 5',
    'options': '-vn'
}

# --- 全局播放器管理 ---
players: Dict[int, "MusicPlayer"] = {}

class MusicPlayer:
    def __init__(self, interaction: discord.Interaction):
        self.bot = interaction.client
        self.guild = interaction.guild
        self.channel = interaction.channel
        self.queue: asyncio.Queue[Dict] = asyncio.Queue()
        self.next = asyncio.Event()
        self.current_song: Dict = None
        self.task = self.bot.loop.create_task(self.player_loop())

    async def player_loop(self):
        await self.bot.wait_until_ready()
        while not self.bot.is_closed():
            self.next.clear()
            self.current_song = None

            try:
                item = await asyncio.wait_for(self.queue.get(), timeout=300)
            except asyncio.TimeoutError:
                await self.destroy()
                return

            self.current_song = item

            try:
                def extractor():
                    # 在独立的线程中运行，以避免阻塞事件循环
                    with yt_dlp.YoutubeDL(YDL_OPTIONS) as ydl:
                        # 提取包括http_headers在内的完整信息
                        info = ydl.extract_info(item['webpage_url'], download=False)
                        if 'entries' in info and info['entries']:
                            info = info['entries'][0]
                        return info

                # 即时获取包含URL和头部的完整信息
                info = await self.bot.loop.run_in_executor(None, extractor)
                stream_url = info.get('url')

                if not stream_url:
                    await self.channel.send(f"无法获取音频流，已跳过：**{item.get('title', '未知标题')}**")
                    self.next.set()
                    await self.next.wait()
                    continue

                # 准备带有认证头部的 FFMPEG 选项
                custom_ffmpeg_options = FFMPEG_OPTIONS.copy()
                if info.get('http_headers'):
                    headers_str = "\r\n".join([f"{key}: {value}" for key, value in info['http_headers'].items()])
                    # 转义 headers 字符串中的双引号，以便 ffmpeg 正确解析
                    escaped_headers_str = headers_str.replace('"', '\\"')
                    
                    before_options = custom_ffmpeg_options.get('before_options', '')
                    custom_ffmpeg_options['before_options'] = (
                        before_options + f' -headers "{escaped_headers_str}"'
                    ).strip()

                # 直接使用构造函数，并传入包含认证头部的自定义ffmpeg选项
                source = discord.FFmpegOpusAudio(stream_url, **custom_ffmpeg_options)
                if self.guild.voice_client:
                    self.guild.voice_client.play(source, after=lambda e: self.bot.loop.call_soon_threadsafe(self.next.set))
                    await self.channel.send(f"正在播放：**{item.get('title', '未知标题')}**")
                else:
                    self.next.set()
                
                await self.next.wait()
            except Exception as e:
                await self.channel.send(f"播放出错：{str(e)}")
                self.next.set()

    async def destroy(self):
        self.task.cancel()
        if self.guild.voice_client:
            if self.guild.voice_client.source:
                self.guild.voice_client.source.cleanup()
            await self.guild.voice_client.disconnect()
        players.pop(self.guild.id, None)

# --- UI 视图 ---
class MusicDashboard(discord.ui.View):
    def __init__(self, cog: "Music"):
        super().__init__(timeout=3600)
        self.cog = cog

    @discord.ui.button(label="搜索歌曲", style=discord.ButtonStyle.primary, emoji="🔍")
    async def search_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(SearchModal(self.cog))

    @discord.ui.button(label="直接播放", style=discord.ButtonStyle.secondary, emoji="▶️")
    async def play_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await interaction.response.send_modal(PlayModal(self.cog))

    @discord.ui.button(label="查看列表", style=discord.ButtonStyle.secondary, emoji="📜")
    async def queue_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        await self.cog.show_queue(interaction)

    @discord.ui.button(label="跳过", style=discord.ButtonStyle.secondary, emoji="⏭️")
    async def skip_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        vc = interaction.guild.voice_client
        if vc and vc.is_playing():
            vc.stop()
            await interaction.response.send_message("已跳过当前曲目", ephemeral=True)
        else:
            await interaction.response.send_message("当前没有正在播放的歌曲", ephemeral=True)

    @discord.ui.button(label="停止并离开", style=discord.ButtonStyle.danger, emoji="⏹️")
    async def stop_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        if interaction.guild.id in players:
            player = players[interaction.guild.id]
            player.queue = asyncio.Queue()  # 清空队列
            if interaction.guild.voice_client:
                if interaction.guild.voice_client.is_playing():
                    interaction.guild.voice_client.stop()
                await interaction.guild.voice_client.disconnect()
            await player.destroy()
            await interaction.response.send_message("已停止并离开语音频道", ephemeral=True)
        else:
            await interaction.response.send_message("当前没有音乐播放", ephemeral=True)

class SearchView(discord.ui.View):
    def __init__(self, results: List[Dict], cog: "Music"):
        super().__init__(timeout=180)
        self.results = results
        self.cog = cog

        for i, res in enumerate(results[:25]):  # Discord 按钮上限
            btn = discord.ui.Button(label=res['title'][:80], style=discord.ButtonStyle.secondary, custom_id=str(i))
            btn.callback = self.select_song
            self.add_item(btn)

    async def select_song(self, interaction: discord.Interaction):
        idx = int(interaction.data['custom_id'])
        song = self.results[idx]
        if not interaction.user.voice:
            return await interaction.response.send_message("请先加入语音频道", ephemeral=True)

        # Ensure the bot joins the user's voice channel.
        await self.cog._ensure_voice(interaction)

        await interaction.response.send_message(f"正在添加：**{song['title']}**", ephemeral=True)
        await self.cog.add_to_queue(interaction, song)

        self.clear_items()
        try:
            await interaction.message.edit(view=self)
        except discord.errors.NotFound:
            # The message was likely deleted or is otherwise unavailable.
            # This can happen with ephemeral messages, just ignore it.
            pass
        self.stop()

class QueueView(discord.ui.View):
    def __init__(self, player: MusicPlayer):
        super().__init__(timeout=180)
        self.player = player

        items = list(player.queue._queue)
        for i, song in enumerate(items[:25]):
            btn = discord.ui.Button(label=f"{i+1}. {song['title'][:70]}", custom_id=str(i))
            btn.callback = self.move_to_top
            self.add_item(btn)

    async def move_to_top(self, interaction: discord.Interaction):
        idx = int(interaction.data['custom_id'])
        q = list(self.player.queue._queue)
        song = q.pop(idx)
        new_q = asyncio.Queue()
        await new_q.put(song)
        for item in q:
            await new_q.put(item)
        self.player.queue = new_q

        if interaction.guild.voice_client and interaction.guild.voice_client.is_playing():
            interaction.guild.voice_client.stop()

        await interaction.response.edit_message(content=f"已将 **{song['title']}** 移到最前面并开始播放", view=None)
        self.stop()

# --- 输入框 ---
class SearchModal(discord.ui.Modal, title="搜索 YouTube 歌曲"):
    query = discord.ui.TextInput(label="关键词", placeholder="例如：周杰伦 晴天")

    def __init__(self, cog: "Music"):
        super().__init__()
        self.cog = cog

    async def on_submit(self, interaction: discord.Interaction):
        await self.cog.search_and_display(interaction, self.query.value)

class PlayModal(discord.ui.Modal, title="直接播放"):
    query = discord.ui.TextInput(label="关键词或链接")

    def __init__(self, cog: "Music"):
        super().__init__()
        self.cog = cog

    async def on_submit(self, interaction: discord.Interaction):
        await self.cog.play_now(interaction, self.query.value)

# --- 主 Cog 类 ---
class Music(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot

    async def _ensure_voice(self, interaction: discord.Interaction) -> bool:
        if not interaction.user.voice:
            await interaction.response.send_message("请先加入语音频道", ephemeral=True)
            return False
        channel = interaction.user.voice.channel
        if interaction.guild.voice_client:
            await interaction.guild.voice_client.move_to(channel)
        else:
            await channel.connect()
        return True

    def get_player(self, interaction: discord.Interaction) -> MusicPlayer:
        gid = interaction.guild.id
        if gid not in players:
            players[gid] = MusicPlayer(interaction)
        return players[gid]

    async def add_to_queue(self, interaction: discord.Interaction, song: Dict):
        player = self.get_player(interaction)
        await player.queue.put(song)
        await interaction.followup.send(f"已加入队列：**{song.get('title', '未知')}**", ephemeral=True)

    async def search_and_display(self, interaction: discord.Interaction, query: str):
        await interaction.response.defer(ephemeral=True)

        def extract():
            url = f"ytsearch10:{query}"  # 使用 yt-dlp 支持的 YouTube 搜索前缀，返回前 10 个结果
            ydl_opts = YDL_OPTIONS.copy()
            ydl_opts['extract_flat'] = True
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                return ydl.extract_info(url, download=False)

        try:
            info = await self.bot.loop.run_in_executor(None, extract)
            entries = info.get('entries', [])[:10]
            if not entries:
                await interaction.followup.send("未找到结果", ephemeral=True)
                return

            results = []
            for e in entries:
                results.append({
                    'title': e.get('title', '未知标题'),
                    'webpage_url': e.get('url') or e.get('webpage_url'),
                    'id': e.get('id')
                })

            view = SearchView(results, self)
            await interaction.followup.send("搜索结果（前10）", view=view, ephemeral=True)
        except Exception as e:
            await interaction.followup.send(f"搜索失败：{str(e)}", ephemeral=True)

    async def play_now(self, interaction: discord.Interaction, query: str):
        if not await self._ensure_voice(interaction):
            return

        await interaction.response.defer(ephemeral=True)

        def extract():
            ydl_opts = YDL_OPTIONS.copy()
            ydl_opts['playlistend'] = 1
            if query.startswith(('http', 'https')):
                url = query
            else:
                url = f"ytsearch:{query}"  # 使用 yt-dlp 支持的 YouTube 搜索前缀，取第一个结果
            with yt_dlp.YoutubeDL(ydl_opts) as ydl:
                info = ydl.extract_info(url, download=False)
                if 'entries' in info and info['entries']:
                    return info['entries'][0]
                return info

        try:
            entry = await self.bot.loop.run_in_executor(None, extract)
            if not entry or not entry.get('webpage_url'):
                await interaction.followup.send("未找到可播放内容", ephemeral=True)
                return

            song = {
                'title': entry.get('title', '未知'),
                'webpage_url': entry.get('webpage_url') or entry.get('url')
            }
            await self.add_to_queue(interaction, song)
        except Exception as e:
            await interaction.followup.send(f"直接播放失败：{str(e)}", ephemeral=True)

    async def show_queue(self, interaction: discord.Interaction):
        if interaction.guild.id not in players:
            await interaction.response.send_message("当前没有播放列表", ephemeral=True)
            return

        player = players[interaction.guild.id]
        embed = discord.Embed(title="播放队列", color=0x5865F2)

        if player.current_song:
            embed.add_field(name="正在播放", value=player.current_song.get('title', '未知'), inline=False)

        q_list = list(player.queue._queue)
        if q_list:
            embed.add_field(
                name="等待队列",
                value="\n".join(f"{i+1}. {s.get('title','未知')}" for i, s in enumerate(q_list[:15])),
                inline=False
            )

        view = QueueView(player)
        await interaction.response.send_message(embed=embed, view=view, ephemeral=True)

    @app_commands.command(name="music", description="打开音乐控制面板")
    async def music_panel(self, interaction: discord.Interaction):
        embed = discord.Embed(title="音乐控制面板", color=0xFF69B4)
        view = MusicDashboard(self)
        await interaction.response.send_message(embed=embed, view=view)

async def setup(bot):
    await bot.add_cog(Music(bot))
