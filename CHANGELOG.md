# Changelog

## v0.3.1-alpha

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
