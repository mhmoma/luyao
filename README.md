# 璐瑶（Luyao）Discord Bot

人设向 Discord 机器人：AI 对话、绘图，以及（可选）音乐等能力。角色设定见 [`persona.md`](persona.md)。

## 功能概览

- OpenAI 兼容 API 对话
- AI 绘图
- Docker / docker-compose 一键部署
- 频道白名单、管理员与亲密用户等可控开关（环境变量）

## 环境要求

- Python 3.8+
- （音乐功能）FFmpeg、PyNaCl 等，见 `requirements.txt` / 历史 README 说明

## 快速开始

```bash
git clone https://github.com/mhmoma/luyao.git
cd luyao
pip install -r requirements.txt
# 配置环境变量（见 docker-compose.yml 中的说明项）
# 至少需要：DISCORD_TOKEN、OPENAI_API_BASE、OPENAI_API_KEY、OPENAI_MODEL_NAME
python main.py
```

### Docker Compose

```bash
# 编辑 docker-compose.yml 或使用 .env 注入密钥
docker compose up -d --build
```

## 目录

| 路径 | 说明 |
|------|------|
| `main.py` | 入口 |
| `bot/` | 机器人模块 |
| `ai/` | AI 相关逻辑 |
| `persona.md` | 人设 |
| `settings/` | 配置 |
| `docker-compose.yml` | 容器部署 |

## 安全提示

- Token / API Key / 用户 ID 仅放在本地 `.env` 或编排环境变量中，勿提交到 Git
- 公开仓库请定期检查是否误传敏感信息
