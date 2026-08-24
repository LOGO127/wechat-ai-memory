# JSON 数据格式

微信 AI 记忆库使用 Version 1 JSON 作为稳定的交换格式。输入文件必须使用 UTF-8，时间使用 ISO 8601；图片和文件路径既可以是绝对路径，也可以相对于 JSON 文件。

## 完整示例

```json
{
  "version": 1,
  "conversations": [
    {
      "id": "project-group",
      "name": "项目讨论群",
      "kind": "group",
      "messages": [
        {
          "id": "m001",
          "sender": "张三",
          "timestamp": "2026-08-21T22:15:00",
          "type": "text",
          "content": "workflow 跑得怎么样？"
        },
        {
          "id": "m002",
          "sender": "李四",
          "timestamp": "2026-08-21T22:16:00",
          "type": "image",
          "content": "assets/result.png",
          "is_outgoing": true,
          "reply_to": "m001"
        }
      ]
    }
  ]
}
```

仓库中的 [`examples/demo_chat.json`](../examples/demo_chat.json) 提供了包含文本、图片、文件和系统消息的可运行样例。

## 顶层字段

| 字段 | 类型 | 必需 | 说明 |
| --- | --- | :---: | --- |
| `version` | integer | 是 | 当前固定为 `1` |
| `conversations` | array | 是 | 会话列表，不能为空 |

## 会话字段

| 字段 | 类型 | 必需 | 说明 |
| --- | --- | :---: | --- |
| `id` | string | 是 | 文件内稳定唯一的会话标识 |
| `name` | string | 是 | 联系人或群聊的展示名称 |
| `kind` | string | 否 | `direct` 或 `group`，默认 `direct` |
| `messages` | array | 是 | 按时间排列的消息列表 |

## 消息字段

| 字段 | 类型 | 必需 | 说明 |
| --- | --- | :---: | --- |
| `id` | string | 是 | 文件内全局唯一的消息标识 |
| `sender` | string | 是 | 发送者展示名称 |
| `timestamp` | string | 是 | ISO 8601 时间；带时区时转换为本机时间 |
| `type` | string | 否 | `text`、`image`、`file` 或 `system`，默认 `text` |
| `content` | string | 是 | 文本内容，或图片、文件的本地路径 |
| `is_outgoing` | boolean | 否 | `true` 表示由当前用户发送 |
| `reply_to` | string | 否 | 被引用消息的 `id` |

## 校验行为

- 未知的 `version` 会被拒绝。
- 重复的会话 ID 或消息 ID 会被拒绝。
- 无法解析的时间、消息类型和缺失必需字段会产生明确错误。
- 相对附件路径以 JSON 文件所在目录为基准解析。
