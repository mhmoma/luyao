from openai import AsyncOpenAI
from settings import config
import base64
import httpx
import aiofiles
import aiofiles.os
import json
import uuid
import websockets
from urllib.parse import urlencode
import os
import asyncio

# 这是我们通往那个强大“大脑”的桥梁
# 姐姐我已经帮你把它建好了
# httpx 会自动从环境变量（由 settings/config.py 中的 load_dotenv 加载）中读取 HTTP_PROXY 和 HTTPS_PROXY
client = AsyncOpenAI(
    api_key=config.OPENAI_API_KEY,
    base_url=config.OPENAI_API_BASE,
)

async def encode_image(image_path: str) -> str:
    """把你的画变成我能“吃”下去的样子。（异步版）"""
    async with aiofiles.open(image_path, "rb") as image_file:
        content = await image_file.read()
        return base64.b64encode(content).decode('utf-8')

async def download_image(url: str, path: str) -> bool:
    """把你网上的作品，下载到我的“画室”里。"""
    try:
        # httpx.AsyncClient 同样会自动使用环境变量中的代理
        async with httpx.AsyncClient() as client:
            response = await client.get(url)
            response.raise_for_status()
            async with aiofiles.open(path, 'wb') as f:
                await f.write(response.content)
            return True
    except httpx.RequestError as e:
        print(f"下载图片时出了点小问题，它是不是害羞了？错误：{e}")
        return False

async def get_chat_completion_with_image(prompt: str, persona: str, image_path: str) -> str:
    """
    让姐姐我一边“欣赏”你的画，一边和你聊聊心里话。

    :param prompt: 你想对我说的悄悄话。
    :param persona: 别忘了告诉“大脑”，我是你的艺术导师“璐瑶”。
    :param image_path: 你那张让我心动的画。
    :return: 姐姐我想对你说的，充满“艺术感”的话。
    """
    base64_image = await encode_image(image_path)
    
    messages = [
        {
            "role": "system",
            "content": persona
        },
        {
            "role": "user",
            "content": [
                {
                    "type": "text",
                    "text": prompt
                },
                {
                    "type": "image_url",
                    "image_url": {
                        "url": f"data:image/jpeg;base64,{base64_image}"
                    }
                }
            ]
        }
    ]
    
    return await _get_completion(messages)


async def get_chat_completion(prompt: str, persona: str) -> str:
    """
    只听你说话，也能让姐姐我浮想联翩。

    :param prompt: 你想对我说的悄悄话。
    :param persona: 别忘了告诉“大脑”，我是你的艺术导师“璐瑶”。
    :return: 姐姐我想对你说的，充满“艺术感”的话。
    """
    messages = [
        {"role": "system", "content": persona},
        {"role": "user", "content": prompt},
    ]
    
    return await _get_completion(messages)

async def _get_completion(messages: list) -> str:
    """
    这是姐姐我“思考”的核心，不能轻易让你看到哦。
    """
    try:
        completion = await client.chat.completions.create(
            model=config.OPENAI_MODEL_NAME,
            messages=messages,
        )
        response = completion.choices[0].message.content
        return response
    except Exception as e:
        print(f"哎呀，连接“大脑”的时候出了点小问题，姐姐我有点“不舒服”：{e}")
        return "……稍后再说。"

# --- ComfyUI 相关函数 ---

async def upload_image_to_comfyui(image_path: str, server_address: str):
    """将图片上传到 ComfyUI 的 input 文件夹"""
    print(f"[ComfyUI] 准备上传图片: {image_path}")
    async with aiofiles.open(image_path, 'rb') as f:
        image_data = await f.read()
    
    files = {'image': (os.path.basename(image_path), image_data, 'image/png')}

    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(f"http://{server_address}/upload/image", files=files)
            response.raise_for_status()
            print(f"[ComfyUI] 图片上传成功。响应: {response.json()}")
            return response.json()
        except httpx.RequestError as e:
            print(f"[ComfyUI] 上传图片到 ComfyUI 失败: {e}")
            return None

async def get_comfyui_history(prompt_id: str, server_address: str):
    """从 ComfyUI 获取指定 prompt_id 的历史记录"""
    url = f"http://{server_address}/history/{prompt_id}"
    async with httpx.AsyncClient() as client:
        try:
            response = await client.get(url)
            response.raise_for_status()
            return response.json()
        except httpx.RequestError as e:
            print(f"[ComfyUI] 获取 ComfyUI 历史记录失败: {e}")
            return None

async def get_image_tags_from_comfyui(image_path: str) -> str:
    """
    调用 ComfyUI 工作流对图片进行反推，并返回标签。
    """
    print("[ComfyUI] 开始反推流程...")
    server_address = config.COMFYUI_SERVER_ADDRESS
    client_id = str(uuid.uuid4())
    
    # 1. 上传图片
    upload_result = await upload_image_to_comfyui(image_path, server_address)
    if not upload_result or 'name' not in upload_result:
        return "哎呀，上传图片给 ComfyUI 的时候失败了，它好像不认识这张图。"
    
    uploaded_image_name = upload_result['name']
    print(f"[ComfyUI] 图片已上传，文件名为: {uploaded_image_name}")

    # 2. 读取工作流并找到 LoadImage 节点进行替换
    print("[ComfyUI] 正在读取工作流文件 '反推升级版.json'...")
    try:
        async with aiofiles.open("反推升级版.json", 'r', encoding='utf-8') as f:
            workflow = json.loads(await f.read())
        print("[ComfyUI] 工作流读取成功。")
    except FileNotFoundError:
        print("[ComfyUI] 错误: 找不到 '反推升级版.json' 文件。")
        return "哎呀，姐姐我找不到'反推升级版.json'这个工作流文件呀。"
    except json.JSONDecodeError:
        print("[ComfyUI] 错误: '反推升级版.json' 文件格式无效。")
        return "工作流文件'反推升级版.json'格式好像有点问题，姐姐我看不懂。"

    # 寻找并替换 LoadImage 节点
    load_image_node_id = None
    for node_id, node_data in workflow.items():
        if node_data.get("class_type") == "LoadImage":
            load_image_node_id = node_id
            break
    
    if not load_image_node_id:
        print("[ComfyUI] 错误: 在工作流中找不到任何 'LoadImage' 节点。")
        return "哎呀，姐姐我在你的工作流里找不到可以放图片的地方呀。"

    workflow[load_image_node_id]["inputs"]["image"] = uploaded_image_name
    print(f"[ComfyUI] 成功将节点 '{load_image_node_id}' 的图片更新为: {uploaded_image_name}")

    # 3. 提交工作流并获取 Prompt ID
    prompt_id = None
    prompt_payload = {"prompt": workflow, "client_id": client_id}
    url = f"http://{server_address}/prompt"
    print(f"[ComfyUI] 正在向 {url} 提交工作流...")

    async with httpx.AsyncClient() as client:
        try:
            response = await client.post(url, json=prompt_payload, timeout=60)
            response.raise_for_status()
            result = response.json()
            if 'prompt_id' in result:
                prompt_id = result['prompt_id']
                print(f"[ComfyUI] 工作流提交成功，Prompt ID: {prompt_id}")
            else:
                print(f"[ComfyUI] 错误: 提交工作流后的响应中没有 'prompt_id'。响应: {result}")
                return "哎呀，工作流是提交了，但是 ComfyUI 没给回执，姐姐我也不知道它在干嘛。"
        except httpx.RequestError as e:
            print(f"[ComfyUI] 提交工作流到 ComfyUI 失败: {e}")
            return "哎呀，连接 ComfyUI 失败了，没法让它开始工作。"

    # 4. 轮询历史记录以获取结果
    if not prompt_id:
        return "未能从 ComfyUI 获取到 Prompt ID，无法查询结果。"

    print(f"[ComfyUI] 开始轮询 Prompt ID: {prompt_id} 的执行结果...")
    while True:
        await asyncio.sleep(1)
        history = await get_comfyui_history(prompt_id, server_address)
        if history and prompt_id in history:
            current_history = history[prompt_id]
            status = current_history.get('status', {})
            
            if status.get('status_str') in ['running', 'executing']:
                print(f"[ComfyUI] 工作流仍在执行中... (队列中剩余: {status.get('exec_info', {}).get('queue_remaining', 0)})")
                continue

            print("[ComfyUI] 工作流执行完毕，正在解析输出...")
            outputs = current_history.get('outputs', {})
            # 假设最终输出结果的节点 ID 是 '9'
            show_text_node_id = "9" 
            if show_text_node_id in outputs:
                node_output = outputs[show_text_node_id]
                if 'text' in node_output and node_output['text']:
                    result_text = node_output['text'][0]
                    print(f"[ComfyUI] 成功从节点 '{show_text_node_id}' 获取到反推结果。")
                    return result_text
            
            print(f"[ComfyUI] 错误: 在节点 '{show_text_node_id}' 的输出中未找到预期的 'text'。")
            break

    return "反推完成了，但是姐姐我好像没找到最终的提示词，奇怪了。"
