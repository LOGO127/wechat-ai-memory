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

### 控制软件包体积

- WXGF 图片与本地语音共用 PyAV 编解码库，不再额外打包独立的 FFmpeg EXE。
- `imageio` 与 `imageio-ffmpeg` 仅用于制作教学动画，安装 `media` 可选依赖即可；它们被明确排除在用户软件包之外。
- QtGui 打包钩子只排除虚拟键盘和 PDF 图片插件，在分析依赖前阻止无用的 QML、Quick 和 QtPdf 进入软件包。保留 Windows 原生输入、SVG 图标、图片插件及软件 OpenGL 后备库。
- 构建脚本临时隔离 PATH 和 Python 环境变量，只保留项目 Python 与 Windows 系统路径，防止其他开发工具的 ICU、OpenSSL 等 DLL 被自动收集；结束后恢复原环境变量。
- 仍保留 Frida、本地语音推理引擎与 VAD；不能为减小体积直接删除这些功能所需的 DLL。
- Whisper 模型按需下载到用户缓存，本来就不在 EXE 中。下载包体积、解压占用和语音模型缓存应分别衡量。

2026-09-05 本机 Windows x64 构建实测，不含按需下载的 Whisper 模型：

| 项目 | v0.3.7 原软件包 | v0.3.8 本地构建 |
| --- | ---: | ---: |
| 便携 EXE | 210.3 MiB | 169.4 MiB |
| ZIP 下载包 | 216.2 MiB | 173.9 MiB |
| 解压目录 | 550.0 MiB | 439.0 MiB |

便携版减少约 19.5%，未移除微信读取、高清图片、语音转写或导出功能。新包通过了 45 项源码测试，以及目录版、便携版和实际 ZIP 解压版的运行库与 GUI 导出检查。此结果不替代干净 Windows 10/11 机器上的发布兼容性验收；不同依赖版本的构建体积可能变化。

`verify_windows_release.ps1` 会生成 `work/release-smoke/package-sizes.json`，并检查体积上限：便携版 185 MiB、ZIP 195 MiB、解压目录 475 MiB。依赖升级突破上限时，先审计文件明细，再有依据地调整参数。

发布验收还会在移除开发环境 PATH、禁用模型联网下载的子进程中，实际运行两种 EXE，验证 WXGF 逐像素解码、SILK 解码与音频重采样、CPU 推理运行库、Silero VAD 推理。维护者可单独执行：

```powershell
.\.venv-gui\Scripts\python.exe scripts\package_runtime_smoke.py `
  --exe outputs\WeChatAIMemory-Portable.exe `
  --output work\runtime-check\result.json
```

此检查仅使用生成的测试图片和静音音频，不读取真实聊天、不下载 Whisper 模型，也不能替代真实语音识别质量或干净 Windows 环境的兼容性测试。

后续需要进一步缩小时，优先考虑独立的按需语音组件，同时保留供离线用户下载的完整版。模型文件目前已不随 EXE 分发，因此仅更换较小的 Whisper 模型不会减小 EXE 本身；拆分的是推理运行库，需要同步设计组件版本校验、下载失败重试和离线安装。

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
3. 构建软件包后运行 `.\scripts\verify_windows_release.ps1`，完成体积预算、两种 EXE 的编解码与推理运行库检查，以及 GUI 加载、搜索和导出验收。
4. 检查 EXE 图标、文件版本、Release ZIP 和 `SHA256SUMS.txt`。
5. 在干净的 Windows 用户环境中重复启动和导出测试。
6. 确认提交中不含 `outputs/`、`work/`、微信数据库、密钥或真实聊天截图。

`.github/workflows/release.yml` 会在手动触发或推送 `v*` 标签时重新执行上述构建与验收。只有通过全部检查的标签构建才会创建 GitHub Release。
