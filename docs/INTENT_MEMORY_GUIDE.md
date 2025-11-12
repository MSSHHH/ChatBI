## High-Precision NL Querying 与多轮上下文集成指南

本项目已集成“高精度自然语言查询 + 智能意图识别 + 多轮上下文记忆”。本指南说明如何配置、启动与使用，并提供可直接复制的示例（包含多轮追问与上下文引用）。

### 1. 环境准备
- 必要环境变量（可在项目根目录 `.env` 设置，或系统环境变量中设置）：
  - `OPENAI_API_KEY`: 与兼容 OpenAI 接口的 Key
  - `OPENAI_API_BASE_URL`: 默认为 `https://dashscope.aliyuncs.com/compatible-mode/v1`
- 依赖安装：
  - Python 后端（建议使用 `uv` 或 `pip`）：参见 `requirements.txt` 或 `environment.yml`
  - 前端：在 `frontend/` 下执行 `npm i` 或 `pnpm i`

### 2. 启动方式
- 后端（FastAPI）：
  - 参考 `main.py` 或 `backend/server.py` 对应的启动脚本（如 `uvicorn backend.server:create_app --factory --host 0.0.0.0 --port 8000`）
  - 健康检查：`GET http://localhost:8000/api/chat/health`
- 前端（Vite）：
  - 在 `frontend/` 执行 `npm run dev`（或 `pnpm run dev`）
  - 如需指定后端地址，在前端 `.env` 中设置：`VITE_API_BASE_URL=http://localhost:8000`

### 3. 能力概述
- 智能意图识别：
  - 新增工具 `analyze_nl_intent` 将自然语言解析为结构化分析计划（JSON），包含 `select / filters / group_by / having / order_by / limit / time_range / follow_up` 等。
  - 用于约束 NL→SQL 的生成，提升复杂查询（筛选、分组、聚合、排序、时间范围）的稳定性与可控性。
- 上下文记忆：
  - 基于 LangGraph `MemorySaver` 与 `configurable.thread_id=session_id` 实现会话级记忆。
  - 支持“追问/继续/基于刚才的结果”自然表达，自动复用/修改上一轮 SQL 或参数。
- 可视化：
  - 当用户要求“画图/图表/可视化”，Agent 将先执行 SQL 拿数据，再调用 `high_charts_json` 返回 Highcharts 配置，前端可直接渲染。

### 4. 接口约定（SSE）
- 路径：`POST /api/chat/query`
- 请求体：
```json
{
  "query": "自然语言问题",
  "session_id": "可选，不传则默认default",
  "request_id": "可选，不传则后端生成",
  "model": "qwen-plus"
}
```
- 响应：SSE 流式事件，`event: message`，`data` 为 JSON：
  - `type`: `start | response | error`
  - `message`: 文本内容（`response` 时累积/最终内容）
  - `finished`: 是否结束（最终一次 `true`）

示例 cURL：
```bash
curl -N -X POST "http://localhost:8000/api/chat/query" \
  -H "Content-Type: application/json" \
  -d '{"query":"统计2025年每月的订单数量","session_id":"demo-1"}'
```

### 5. 前端使用
- `frontend/src/utils/querySSE.ts` 使用 `@microsoft/fetch-event-source` 建立 SSE 连接，消费 `type: start|response|error` 事件。
- `frontend/src/components/ChatView/index.tsx` 的 `sendMessage` 会传入 `session_id`，确保同一会话内的记忆生效。

### 6. 使用示例（可直接复制）

#### 6.1 单轮复杂查询（高精度）
用户输入：
> 筛选2025年内的订单，按客户分组统计总金额和订单数，按总金额倒序取前10

系统行为（简述）：
1) `analyze_nl_intent` 解析出 filters/time_range/group_by/aggregations/order_by/limit 等结构化计划；
2) 必要时 `database_schema_rag` 检索表结构；
3) `text2sqlite_query` 生成 SQL；
4) `execute_sqlite_query` 返回结果；
5) 以表格/摘要呈现关键发现与所用分组/排序条件。

#### 6.2 多轮追问（修改上轮 SQL）
轮1：
> 统计2025年每个月的订单数量与销售额，并按月份升序

轮2（追问，复用上轮语义）：
> 只看上次结果里销售额大于10000的月份

轮3（继续修改）：
> 改为比较2024年和2025年上半年，每个月的订单数量

系统行为（简述）：
- 通过 `session_id` 维持记忆，`analyze_nl_intent` 的 `follow_up` 字段会指示“使用上轮 SQL 并修改条件/时间范围/分组方式”。
- Agent 自动生成新的 SQL 并给出更新后的结果。

#### 6.3 多轮 + 可视化
轮1：
> 2025年每个月的销售额趋势，画折线图

轮2（追问）：
> 同样画出订单数量的折线图并与销售额在同一图里对比

系统行为（简述）：
- 轮1生成 SQL 查询数据，并调用 `high_charts_json` 返回折线图配置；
- 轮2在复用“月份粒度”的前提下追加/组合数据系列，返回多序列配置，前端直接渲染。

### 7. session_id 与上下文
- 会话标识 `session_id` 决定上下文范围；同一个 `session_id` 下的多轮对话会共享记忆。
- 前端默认使用固定 `session_id`（或在新对话/Tab 时生成唯一值）；后端通过 `configurable.thread_id=session_id` 使用 `MemorySaver` 维护上下文。

### 8. 常见问题
- 提示“API Key 未设置”：请检查 `OPENAI_API_KEY` 是否正确配置。
- SQL 字段不匹配：请确认 `tools/example.db` 的表结构是否与问题字段一致；必要时先询问/检索 schema（项目内 docs/* 提供示例结构）。
- 需要多数据库：可扩展 `tools_execute_sqlite.py` 支持多库路由（在请求体中加入 `db_id` 并在 Agent 中透传）。

### 9. 二次开发建议
- 在 `tools/tools_intent.py` 增加“指标/口径别名库”，统一业务口径；
- 在 Agent 中将“上轮 SQL/结果列结构”以工具消息形式入库，支持更强的上下文引用；
- 扩充 `high_charts_json` 支持更多图型与自动推荐。



