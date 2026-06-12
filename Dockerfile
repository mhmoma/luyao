# 使用更完整的Python运行时作为父镜像
FROM python:3.11-bookworm

# 安装 ffmpeg
RUN apt-get update && apt-get install -y ffmpeg

# 设置工作目录
WORKDIR /app

# 将当前目录内容复制到容器中的/app
COPY . /app

# 安装任何所需的包
RUN pip install --no-cache-dir -r requirements.txt

# 在容器启动时设置DNS，然后运行机器人
CMD sh -c "echo 'nameserver 8.8.8.8' > /etc/resolv.conf && python main.py"
