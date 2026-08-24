# Changelog

## v0.3.2-alpha

### Fixed

- 让“读取图片”成功状态在消息刷新后仍清晰可见。
- 为源码测试设置独立 Qt 模式，减少全局 Python 插件的环境干扰。

### Verified

- 从 GitHub 重新下载并校验 ZIP 与单文件版的 SHA-256。
- 两种 Windows 软件包完成 GUI 加载、搜索、PDF、PNG、Markdown 和 JSON 导出闭环。
- Windows 微信 4.1.2.18 完成真实数据库密钥、会话、消息和 V2 图片解密验证。
- 新增发布工作流，标签资产必须先通过打包后 GUI 验收。

## v0.3.1-alpha

### Added

- 提供无需解压的 `WeChatAIMemory-Portable.exe` 单文件版本。
- 在 README 中加入可循环播放、可点击查看高清版的使用教学动画。

### Fixed

- 让伴随 JSON 使用 Version 1 交换结构，支持再次导入。
- 让关键词搜索同时作用于预览、PDF、Markdown 和 JSON。
- 将图片和文件附件复制到持久化 `_assets` 目录，避免临时路径在退出后失效。
- 正确解析 JSON 中的相对文件附件路径。
- 严格校验 `is_outgoing`、发送者和引用 ID 等 JSON 字段类型。
- 拒绝开始时间晚于结束时间的导出。
- 拒绝 PDF、Markdown、JSON 或分页目录使用冲突路径，避免互相覆盖。

### Verified

- CLI 列表与筛选导出闭环。
- JSON 导出、重新导入和附件独立性。
- PySide6 后台加载、搜索和导出流程。
- PyInstaller 构建、ZIP 解压和独立 EXE 启动。

## v0.3.0-alpha

- 首个私人测试版本。
- 支持 Windows 微信 4.x 本机读取与 JSON 输入。
- 支持会话、日期与关键词预览，以及 PDF、Markdown、JSON 和分页 PNG 输出。
- 提供 Windows 目录版软件包、品牌资源和 GitHub Actions 测试。
