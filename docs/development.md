# 开发文档

## 环境要求

- Windows 10/11 x64
- Python 3.11 或更高版本
- Windows 微信 4.x，仅本机数据适配器需要

建议使用项目独立的 `.venv-gui`，避免 Conda 环境中的 Qt DLL 与 PySide6 冲突。

## 安装与启动

```powershell
py -3 -m venv .venv-gui
.\.venv-gui\Scripts\python.exe -m pip install -e ".[gui,dev]"
.\.venv-gui\Scripts\python.exe app.py
```

项目已存在 `.venv-gui` 时，`python app.py` 会自动切换到该环境。也可以双击 `start.cmd`。

## 测试

```powershell
.\.venv-gui\Scripts\python.exe -m pytest
```

测试覆盖 JSON 校验和日期筛选、分页消息完整性、图片页插入、PDF 页数、数据库页解密、微信 V2 图片恢复、本地联系人和消息映射，以及 Markdown 和 JSON 伴随文件。

## 构建 Windows 软件包

```powershell
.\scripts\build_windows.ps1
```

脚本会安装 `build` 依赖、生成多尺寸 Windows 图标，同时构建目录版和单文件版：

```text
dist/WeChatAIMemory/WeChatAIMemory.exe
outputs/WeChatAIMemory-Windows-x64.zip
outputs/WeChatAIMemory-Portable.exe
```

目录版保留 Qt、Frida 及其 DLL 结构，优先保证兼容性和启动速度；单文件版便于直接下载试用。正式公开发布前仍需完成 Windows 代码签名。

## README 教学动画

教学动画只使用 `examples/demo_chat.json` 的演示数据，不会连接或读取本机微信：

```powershell
python -m pip install -e ".[gui,media]"
python scripts\generate_readme_tutorial.py
```

脚本会生成 README 内联使用的 GIF，以及点击动画后打开的高清 MP4。

## 代码结构

```text
src/wechat_context_exporter/
├── sources/       # JSON 与 Windows 微信 4.x 数据适配器
├── rendering/     # 聊天页、图片页、字体与版式
├── ui/            # PySide6 桌面界面
├── models.py      # Conversation 与 Message 数据模型
├── service.py     # 导出编排
├── pdf_exporter.py
└── text_exporters.py
```

所有数据入口实现 `sources/base.py` 中的 `ChatSource` 协议。渲染器和导出服务不依赖微信内部数据库格式。

## 发布检查

1. 更新 `pyproject.toml`、`src/wechat_context_exporter/__init__.py` 和 Windows 版本资源中的版本号。
2. 运行完整测试。
3. 构建目录版软件包并在干净的 Windows 用户环境中启动。
4. 检查 EXE 图标、文件版本和 Release ZIP。
5. 确认提交中不含 `outputs/`、`work/`、微信数据库、密钥或真实聊天截图。
