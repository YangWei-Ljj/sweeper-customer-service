# MCP 适配层

外部能力（如天气）通过标准协议 MCP 接入，而不是硬编码 Python 函数。`ToolProvider` 抽象让"本地函数"与"MCP 工具"对上层保持同一接口，切换时不用改治理层与 Agent。

## 接口契约

- `list_tools() -> list[ToolInfo(name, description, json_schema)]`
- `call(name, args: dict) -> str`
- `is_connected() -> bool`

## stdio 连接方式

- 传输：stdio（client 拉起 server 子进程，JSON-RPC 经 stdin/stdout，不占端口）。
- 初始化：`ClientSession(read, write)` → `await initialize()`。
- 列举：`list_tools()` → 取 `tools[].name / description / inputSchema`。
- 调用：`call_tool(name, arguments=args)` → 取 `content[].text` 拼接。
- 服务器路径由环境变量 `WEATHER_MCP_SERVER` 指定（指向 server.py 的绝对路径）；未配置时天气工具返回受控错误，不影响其余功能。

## 使用步骤

1. 部署一个实现 `get_weather(location)` 的 MCP server（stdio）。
2. 在 `.env` 里配置 `WEATHER_MCP_SERVER=<server.py 绝对路径>`，如需上游令牌再加 `WEATHER_API_TOKEN`。
3. 启动后即可在问答中触发天气工具；调用会记入执行轨迹（脱敏入参、耗时、状态）。

## 边界

- 不伪造工具返回：server 未配置或调用失败时，向模型返回受控错误，由模型决定是否降级作答。
- MCP 调用与本地工具走同一套权限与审批治理。
