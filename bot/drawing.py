import discord
import aiohttp
import asyncio
import base64
import io
import logging
from discord.ext import commands
from discord import app_commands
from typing import Optional, NamedTuple

from settings.config import IDLECLOUD_API_KEY, API_BASE_URL, HTTP_PROXY

# --- 数据结构 ---
class DrawingTask(NamedTuple):
    interaction: discord.Interaction
    view: "DrawingView"

# --- API 请求相关 ---
HEADERS = {
    "Authorization": f"Bearer {IDLECLOUD_API_KEY}",
    "Content-Type": "application/json"
}

# --- 提示词输入模态框 ---
class PromptModal(discord.ui.Modal, title="填写绘画提示词"):
    positive_prompt = discord.ui.TextInput(label="✨ 正向提示词", style=discord.TextStyle.paragraph, placeholder="你希望在图像中看到的内容...", required=True)
    negative_prompt = discord.ui.TextInput(label="🚫 反向提示词", style=discord.TextStyle.paragraph, placeholder="你不希望在图像中看到的内容...", required=False, default="lowres, bad anatomy, bad hands, text, error, missing fingers, extra digit, fewer digits, cropped, worst quality, low quality, normal quality, jpeg artifacts, signature, watermark, username, blurry")

    def __init__(self, view: "DrawingView"):
        super().__init__()
        self.view = view

    async def on_submit(self, interaction: discord.Interaction):
        self.view.positive_prompt = self.positive_prompt.value
        self.view.negative_prompt = self.negative_prompt.value
        
        self.view.disable_all_items()
        await self.view.message.edit(content="⏳ 参数已锁定，准备提交任务...", view=self.view)

        task = DrawingTask(interaction=interaction, view=self.view)
        queue_position = self.view.cog.drawing_queue.qsize() + 1
        await self.view.cog.drawing_queue.put(task)
        
        await interaction.response.send_message(f"✅ 您的任务已成功提交，当前排在队列第 **{queue_position}** 位。", ephemeral=True)

# --- 参数设置视图 ---
class DrawingView(discord.ui.View):
    def __init__(self, cog: "Drawing"):
        super().__init__(timeout=300)
        self.cog = cog
        self.message: Optional[discord.Message] = None
        self.model, self.width, self.height, self.sampler, self.steps, self.scale = "nai-diffusion-3", 1024, 1024, "k_euler", 28, 5.0
        self.seed: Optional[int] = None
        self.positive_prompt, self.negative_prompt = "", ""

    def disable_all_items(self):
        for item in self.children:
            if isinstance(item, (discord.ui.Button, discord.ui.Select)): item.disabled = True

    @discord.ui.select(placeholder="选择模型 (默认: NAI v3)", options=[discord.SelectOption(label="NAI Diffusion 3", value="nai-diffusion-3"), discord.SelectOption(label="NAI Diffusion 4.5 Full", value="nai-diffusion-4-5-full")])
    async def model_select(self, i: discord.Interaction, s: discord.ui.Select): self.model = s.values[0]; await i.response.defer()
    @discord.ui.select(placeholder="选择尺寸 (默认: 方形)", options=[discord.SelectOption(label="方形 (1024x1024)", value="1024x1024"), discord.SelectOption(label="横向 (1216x832)", value="1216x832"), discord.SelectOption(label="纵向 (832x1216)", value="832x1216")], row=1)
    async def size_select(self, i: discord.Interaction, s: discord.ui.Select): w, h = s.values[0].split('x'); self.width, self.height = int(w), int(h); await i.response.defer()
    
    @discord.ui.select(
        placeholder="设置步数 (默认: 28)",
        options=[
            discord.SelectOption(label="15", value="15"),
            discord.SelectOption(label="20", value="20"),
            discord.SelectOption(label="28", value="28"),
            discord.SelectOption(label="35", value="35"),
        ],
        row=2
    )
    async def steps_select(self, i: discord.Interaction, s: discord.ui.Select): self.steps = int(s.values[0]); await i.response.defer()

    @discord.ui.select(
        placeholder="设置 CFG Scale (默认: 5.0)",
        options=[
            discord.SelectOption(label="3.0", value="3.0"),
            discord.SelectOption(label="5.0", value="5.0"),
            discord.SelectOption(label="7.0", value="7.0"),
            discord.SelectOption(label="10.0", value="10.0"),
        ],
        row=3
    )
    async def scale_select(self, i: discord.Interaction, s: discord.ui.Select): self.scale = float(s.values[0]); await i.response.defer()

    @discord.ui.button(label="📝 填写提示词并开始生成", style=discord.ButtonStyle.primary, row=4)
    async def prompt_button(self, i: discord.Interaction, b: discord.ui.Button): await i.response.send_modal(PromptModal(self))

# --- Cog 定义 ---
class Drawing(commands.Cog):
    def __init__(self, bot: commands.Bot):
        self.bot = bot
        self.session = aiohttp.ClientSession(headers=HEADERS)
        self.proxy = HTTP_PROXY
        self.drawing_queue = asyncio.Queue()
        self.consumer_task = self.bot.loop.create_task(self.consume_drawing_requests())

    async def cog_unload(self):
        await self.session.close()
        self.consumer_task.cancel()

    async def consume_drawing_requests(self):
        await self.bot.wait_until_ready()
        while not self.bot.is_closed():
            try:
                task: DrawingTask = await self.drawing_queue.get()
                await self.process_drawing_request(task.interaction, task.view)
                self.drawing_queue.task_done()
            except asyncio.CancelledError:
                break
            except Exception as e:
                logging.error(f"处理队列任务时发生未知错误: {e}", exc_info=True)

    async def process_drawing_request(self, interaction: discord.Interaction, view: DrawingView):
        await view.message.edit(content="⚙️ 轮到您了！正在提交任务至 API…")
        submit_status, job_id_or_error = await self.submit_generation_task(view)
        if submit_status != "job_submitted":
            await view.message.edit(content=f"❌ **任务提交失败。**\n原因: `{job_id_or_error}`", view=None)
            return
        job_id = job_id_or_error
        await view.message.edit(content=f"✅ 任务已提交 (Job ID: `{job_id}`)… 正在轮询结果。")
        poll_status, result_content = await self.poll_result_task(job_id)
        if poll_status == "completed":
            try:
                image_data = base64.b64decode(result_content)
                image_file = discord.File(io.BytesIO(image_data), filename="generated_image.png")
                await view.message.edit(content=f"✨ **生成完成!** (由 {interaction.user.mention} 触发)\n**Prompt:** `{view.positive_prompt}`", attachments=[image_file], view=None)
            except Exception as e:
                await view.message.edit(content=f"❌ **图像处理失败。**\n原因: `解码或发送文件时出错: {e}`", view=None)
        else:
            await view.message.edit(content=f"❌ **图像生成失败。**\n原因: `{poll_status}`", view=None)

    async def submit_generation_task(self, view: DrawingView) -> tuple[str, str | None]:
        payload = {
            "model": view.model, "positivePrompt": view.positive_prompt, "negativePrompt": view.negative_prompt,
            "width": view.width, "height": view.height, "sampler": view.sampler, "steps": view.steps, "scale": view.scale,
            "ucPreset": 1, "qualityToggle": False, "promptGuidanceRescale": 0, "noise_schedule": "karras",
            "sm": False, "sm_dyn": False, "decrisp": False, "variety": False, "n_samples": 1,
            "prefer_brownian": True, "deliberate_euler_ancestral_bug": False, "legacy": False,
            "legacy_uc": False, "legacy_v3_extend": False, "autoSmea": False, "use_coords": False, "use_upscale_credits": False
        }
        if view.seed is not None: payload["seed"] = view.seed
        try:
            async with self.session.post(f"{API_BASE_URL}/generate_image", json=payload, proxy=self.proxy) as response:
                if response.status != 200:
                    error_text = await response.text()
                    return f"提交任务失败: HTTP {response.status} - {error_text}", None
                data = await response.json()
                job_id = data.get("job_id")
                return ("job_submitted", job_id) if job_id else (f"API未返回job_id: {data}", None)
        except Exception as e:
            return f"网络或未知错误: {e}", None

    async def poll_result_task(self, job_id: str) -> tuple[str, str | None]:
        max_retries = 30
        for i in range(max_retries):
            await asyncio.sleep(5)
            try:
                async with self.session.get(f"{API_BASE_URL}/get_result/{job_id}", proxy=self.proxy) as resp:
                    if resp.status != 200: continue
                    data = await resp.json()
                    status = data.get("status")
                    if status == "completed":
                        if b64 := data.get("image_base64"): return "completed", b64
                        if url := data.get("image_url"):
                            async with self.session.get(url, proxy=self.proxy) as img_resp:
                                if img_resp.status == 200:
                                    img_bytes = await img_resp.read()
                                    return "completed", base64.b64encode(img_bytes).decode('utf-8')
                        return "任务完成但无图像数据", None
                    if status == "failed": return f"任务失败: {data.get('error', '未知')}", None
            except Exception as e:
                logging.error(f"轮询错误: {e}")
                continue
        return "超时失败", None

    @app_commands.command(name="imagine", description="使用高级参数面板生成AI图像")
    async def imagine_command(self, interaction: discord.Interaction):
        # 快速响应一个私有消息，防止命令超时
        await interaction.response.send_message("正在为您准备参数面板...", ephemeral=True)

        # 创建视图
        view = DrawingView(self)
        
        # 在频道中发送一个全新的、公开的消息，并附上视图
        # 这是解决“只有自己可见”问题的关键
        public_message = await interaction.channel.send("请在下方设置绘画参数：", view=view)
        
        # 将这个公开消息的引用存入视图，以便后续进行编辑
        view.message = public_message

async def setup(bot: commands.Bot):
    await bot.add_cog(Drawing(bot))
    print("Drawing Cog loaded.")
