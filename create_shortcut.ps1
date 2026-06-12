# 获取当前脚本所在的目录，即项目根目录
$ProjectRoot = $PSScriptRoot

# 获取桌面路径
$DesktopPath = [System.Environment]::GetFolderPath('Desktop')

# 定义快捷方式的完整路径
$ShortcutPath = [System.IO.Path]::Combine($DesktopPath, '启动璐瑶机器人.lnk')

# 创建 WshShell 对象
$WshShell = New-Object -ComObject WScript.Shell

# 创建快捷方式对象
$Shortcut = $WshShell.CreateShortcut($ShortcutPath)

# --- 设置快捷方式属性 ---

# 目标：要执行的批处理文件
$Shortcut.TargetPath = [System.IO.Path]::Combine($ProjectRoot, 'start_bot.bat')

# 工作目录：设置为项目根目录，以确保批处理文件能找到所有相对路径的文件
$Shortcut.WorkingDirectory = $ProjectRoot

# 描述：鼠标悬停在快捷方式上时显示的文字
$Shortcut.Description = "一键启动璐瑶 Discord 机器人"

# (可选) 图标：您可以将一个 .ico 文件放在项目目录中，并在这里指定它
# 例如：$Shortcut.IconLocation = [System.IO.Path]::Combine($ProjectRoot, 'bot_icon.ico')

# 保存快捷方式
$Shortcut.Save()

Write-Host "成功！"
Write-Host "快捷方式 '启动璐瑶机器人.lnk' 已创建在您的桌面上。"
Write-Host "您现在可以通过双击桌面图标来启动机器人了。"
