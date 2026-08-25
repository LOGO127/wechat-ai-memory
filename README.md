<p align="center">
  <img src="docs/images/app-icon.png" width="112" alt="微信 AI 记忆库品牌符号">
</p>

<h1 align="center">微信 AI 记忆库</h1>

<p align="center"><strong>把散落在微信里的对话，整理成属于你的本地记忆。</strong></p>

<p align="center">
  直接读取 Windows 微信 4.x，按会话、日期和关键词筛选，导出 PDF、Markdown 与结构化 JSON。<br>
  聊天内容、图片和数据库密钥全程留在本机。
</p>

<p align="center">
  <a href="https://github.com/LOGO127/wechat-ai-memory/releases/tag/v0.3.6-alpha"><img alt="Release" src="https://img.shields.io/badge/release-v0.3.6--alpha-07a85b?style=flat-square"></a>
  <img alt="Platform" src="https://img.shields.io/badge/platform-Windows%2010%20%7C%2011-2563eb?style=flat-square">
  <a href="https://github.com/LOGO127/wechat-ai-memory/actions/workflows/test.yml"><img alt="Tests" src="https://github.com/LOGO127/wechat-ai-memory/actions/workflows/test.yml/badge.svg"></a>
  <a href="LICENSE"><img alt="License" src="https://img.shields.io/badge/license-MIT-17211c?style=flat-square"></a>
  <img alt="Privacy" src="https://img.shields.io/badge/privacy-local--only-f6b73c?style=flat-square">
</p>

<p align="center">
  <a href="#下载与使用">下载</a> ·
  <a href="#当前能力">功能</a> ·
  <a href="#隐私设计">隐私</a> ·
  <a href="#兼容性与限制">兼容性</a> ·
  <a href="docs/development.md">开发文档</a>
</p>

<p align="center">
  <a href="docs/media/wechat-ai-memory-tutorial.mp4">
    <img src="docs/media/wechat-ai-memory-tutorial.gif" width="960" alt="微信 AI 记忆库使用教学：连接微信、读取图片、筛选消息、生成档案并查看 PDF">
  </a>
</p>

<p align="center"><sub>连接微信 → 读取图片 → 选择记忆范围 → 关键词筛选 → 生成档案 → 查看实际 PDF。点击动画观看高清版本。</sub></p>

> [!IMPORTANT]
> 当前为 `v0.3.6-alpha` 私人测试版。本机微信读取已在 Windows 微信 4.x 上验证，但微信升级可能改变内部数据格式。首次使用前建议备份重要数据。

## 为什么做这个项目

在 Agent 时代，模型能否真正帮上忙，往往取决于它是否理解事情的来龙去脉。项目决策、需求变更、事件进展、关键承诺和关系背景都需要成为上下文；只给模型几句临时描述，它就只能从不完整的信息中猜测。

而对很多人来说，这些上下文并不在项目管理工具或知识库里，而是散落在微信私聊和群聊中。微信 AI 记忆库希望把聊天记录整理成 **Agent 可以读取、检索和引用的个人上下文记忆**：按会话、时间和关键词提取相关记录，输出 PDF、Markdown 与结构化 JSON，让大模型快速理解一个项目或事件，与我们的真实上下文对齐，再协助分析、咨询、总结和处理相关事务。

市面上不少微信导出工具需要付费，闭源产品的数据处理边界也不容易被独立审查。本项目坚持 **开源免费、本地优先、数据不上传**，让每个人都能掌控自己的聊天记录和记忆资产。当前版本先把可靠的数据提取与归档做好；在这层可信数据之上，后续才能继续构建语义检索、RAG、MCP 和 Agent 工作流。

## 当前能力

| 能力 | 当前实现 |
| --- | --- |
| 本机微信读取 | 自动检测 Windows 微信 4.x 账户目录，只读解密临时数据库副本 |
| 记忆筛选 | 搜索联系人或群聊，通过日历选择日期范围，再按关键词筛选 |
| 消息覆盖 | 文本、图片、文件、语音与系统消息 |
| 图片处理 | V2/WXGF 原图恢复、EXIF 方向修正、预览图与 300 DPI 高清独立页 |
| 语音处理 | 读取微信 SILK 音频，使用本地 faster-whisper 转写并缓存文字 |
| 记忆输出 | PDF、Markdown、规范化 JSON，可选分页 PNG |
| 使用方式 | PySide6 桌面界面、JSON 备用入口和命令行 |
| 数据边界 | 无遥测、无远程 API、无聊天内容上传 |

## 下载与使用

### Windows 软件包

从 [v0.3.7-alpha Release](https://github.com/LOGO127/wechat-ai-memory/releases/tag/v0.3.7-alpha) 选择一种方式：

| 下载文件 | 使用方式 | 适合场景 |
| --- | --- | --- |
| `WeChatAIMemory-Portable.exe` | 下载后双击运行，无需安装或解压 | 普通用户，推荐 |
| `WeChatAIMemory-Windows-x64.zip` | 完整解压，再运行目录内的 `WeChatAIMemory.exe` | 启动更快，便于排查安全软件拦截 |

软件包已经包含 Python、Qt、Frida、PDF 与加密运行库，目标电脑不需要安装开发环境。

单文件版首次启动会把运行库释放到 Windows 临时目录，等待十几秒属于正常现象。ZIP 版不能只复制其中的 EXE，必须保留同目录下的 `_internal` 文件夹。

> [!NOTE]
> 当前版本尚未代码签名，Windows SmartScreen 可能显示“未知发布者”。Frida 用于读取当前用户已登录的微信进程，部分安全软件也可能提示风险。请只从本仓库 Release 下载并核对来源。

### 连接本机微信

1. 登录 Windows 微信 4.x，打开微信 AI 记忆库。
2. 确认自动检测出的账户目录，点击“连接微信”。
3. 微信重启后，在 5 分钟内扫码或用手机确认登录。
4. 选择联系人或群聊、日期和关键词。
5. 选择保存位置，点击“生成记忆档案”。

需要原图时点击“读取图片”。旧版微信若未能自动取得图片配置，可先在微信中打开一张聊天原图后重试。

## 隐私设计

| 数据行为 | 是否发生 |
| --- | :---: |
| 上传聊天内容、图片或导出文件 | 否 |
| 遥测、埋点或远程 AI 请求 | 否 |
| 发送、撤回或修改微信消息 | 否 |
| 将数据库密钥写入磁盘 | 否 |
| 解密原始微信数据库文件 | 否，只处理临时副本 |

程序只处理当前 Windows 用户可访问的账户数据。临时数据库和恢复图片位于系统临时目录，并在数据源关闭时删除。安全问题请参阅 [SECURITY.md](SECURITY.md)。

## 兼容性与限制

| 项目 | 当前状态 |
| --- | --- |
| 操作系统 | Windows 10/11 x64 |
| 微信版本 | Windows 微信 4.x，版本升级后可能需要适配 |
| 发布状态 | Alpha，适合个人试用和受控测试 |
| Windows 签名 | 暂无代码签名 |
| AI 问答 / RAG | 尚未实现 |
| OCR | 尚未实现 |
| 语音转写 | 已支持微信 4.x SILK 语音；首次使用需联网下载约 500 MB 的 `small` 模型 |

直接读取微信依赖其内部数据格式，因此“软件能启动”不等于“所有微信版本都能读取”。遇到兼容问题时，请附上 Windows 版本、微信版本和去除隐私信息后的错误日志。

语音转写由本地模型执行，聊天内容和语音不会上传。模型和转写缓存保存在 `%LOCALAPPDATA%\WeChatAIMemory`；首次模型下载完成后可离线使用。

## 从源码运行

需要 Python 3.11 或更高版本：

```powershell
git clone https://github.com/LOGO127/wechat-ai-memory.git
cd wechat-ai-memory
py -3 -m venv .venv-gui
.\.venv-gui\Scripts\python.exe -m pip install -e ".[gui,dev]"
.\.venv-gui\Scripts\python.exe app.py
```

也可以双击 `start.cmd`。完整的测试、打包和目录说明位于 [开发文档](docs/development.md)。

## JSON 与命令行

不连接微信时，可以在 GUI 中选择“JSON 文件”，或者用命令行生成相同的记忆档案：

```powershell
wechat-context-exporter `
  --source examples/demo_chat.json `
  --conversation eco-project `
  --start 2026-08-21 `
  --end 2026-08-22 `
  --output outputs/demo-context.pdf `
  --markdown outputs/demo-context.md `
  --json outputs/demo-context.json
```

交换格式和字段定义请参阅 [JSON 数据格式](docs/json-format.md)。
生成伴随文件时，可用的图片和文件附件会复制到与 PDF 同名的 `_assets` 目录，并在 Markdown 和 JSON 中使用相对路径。

## 工作原理

```text
Windows 微信 4.x ──> 只读临时副本 ──┐
                                    ├─> ChatSource ─> 筛选与预览 ─> PDF / Markdown / JSON
Version 1 JSON ─────────────────────┘
```

微信数据适配器与渲染、导出模块相互隔离。即使微信格式变化，JSON 数据源和输出管线仍可独立工作。

## 路线图

- `v0.4`：持久化记忆库、增量同步、稳定 ID、去重和兼容性诊断
- `v0.5`：SQLite FTS5 全文检索、组合筛选和原消息定位
- `v0.6`：结构化人物、项目、决策、任务与引用关系
- `v0.7`：带原始消息引用的本地 AI 问答
- `v0.8`：只读 MCP 查询接口与更完整的 Windows 发布流程

路线图表达方向，不代表交付承诺。当前实现以 [Release](https://github.com/LOGO127/wechat-ai-memory/releases) 和测试结果为准。

## 参与开发

问题报告和改进建议请先阅读 [CONTRIBUTING.md](CONTRIBUTING.md)，版本变化见 [CHANGELOG.md](CHANGELOG.md)。提交问题时不要上传真实聊天数据库、密钥、联系人名称或未脱敏截图。

## 品牌与声明

绿色对话框代表原始对话，两条索引线代表可检索的上下文，金色圆点代表值得保留的记忆。品牌资源与配色规范见 [品牌指南](docs/brand/README.md)。

本项目为独立开源项目，与腾讯或微信官方无隶属、授权或背书关系。“微信”及相关标识的权利归其权利人所有。

## License

[MIT](LICENSE)
