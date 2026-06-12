# Discord 音乐与AI机器人

这是一个多功能 Discord 机器人，集成了音乐播放、AI 聊天和绘图功能。

## 主要功能

*   **音乐播放**: 从 YouTube 等平台播放音乐。
*   **AI 聊天**: 基于 OpenAI 的模型进行智能对话。
*   **AI 绘图**: 使用 AI 模型生成图片。
*   **Web 服务**: 提供一个简单的 Web 界面。

## 依赖项

项目主要依赖以下 Python 库：

*   `discord.py`: 用于与 Discord API 交互。
*   `python-dotenv`: 用于管理环境变量。
*   `openai`: 用于调用 OpenAI API。
*   `httpx`: HTTP 客户端。
*   `aiofiles`: 用于异步文件操作。
*   `Flask`: 用于 Web 服务。
*   `websockets`: 用于 WebSocket 通信。
*   `yt-dlp`: 用于从 YouTube 下载音频。
*   `PyNaCl`: 用于 Discord 音频加密。

此外，项目运行需要 **Python 3.8+** 和 **FFmpeg**。

## 如何部署

### 1. 克隆仓库

首先，将项目代码从 GitHub 克隆到您的服务器：

```bash
git clone https://github.com/mhmoma/luyao.git
cd luyao
```

### 2. 安装环境依赖

#### a. 安装 Python

确保您的服务器上安装了 Python 3.8 或更高版本。

#### b. 安装 FFmpeg

FFmpeg 是处理音频所必需的。在基于 Debian/Ubuntu 的系统上，可以通过以下命令安装：

```bash
sudo apt update
sudo apt install ffmpeg
```

#### c. 安装 Python 依赖库

使用 `pip` 安装 `requirements.txt` 文件中列出的所有 Python 库：

```bash
pip install -r requirements.txt
```

### 3. 配置环境变量

项目需要一些敏感信息（如 API 密钥和 Token）才能运行。

1.  在项目根目录下，复制 `.env.example` 文件（如果存在）或手动创建一个名为 `.env` 的文件。
2.  编辑 `.env` 文件，填入以下内容：

```env
# 你的 Discord 机器人 Token
DISCORD_BOT_TOKEN="YOUR_DISCORD_BOT_TOKEN"

# 你的 OpenAI API 密钥
OPENAI_API_KEY="YOUR_OPENAI_API_KEY"

# 其他可能需要的配置...
```

**注意**: `.env` 文件包含敏感信息，已在 `.gitignore` 中配置，不会被上传到 Git 仓库。请务必在服务器上手动创建和配置此文件。

### 4. 运行项目

配置完成后，运行主程序 `main.py` 来启动机器人：

```bash
python main.py
```

建议使用进程管理工具（如 `systemd` 或 `supervisor`）来让机器人在后台持续运行。
