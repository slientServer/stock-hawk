# Agents 设计文档

本文档定义智能量化分析系统中所有 AI Agent 的职责、能力、工具、输入输出和协作关系。

## 框架选型：DeerFlow

本系统采用 **DeerFlow** (github.com/bytedance/deer-flow) 作为Multi-Agent框架，基于LangGraph构建。

**DeerFlow核心能力：**
- **Supervisor + Worker 模式**：Orchestrator作为Supervisor自动分解任务并分配给Worker Agent
- **内置工具集**：搜索、爬虫、代码执行等，可直接复用于新闻采集和数据分析
- **Human-in-the-loop**：支持人工审核关键决策（如图谱新实体确认、高风险Alert确认）
- **MCP协议支持**：可扩展接入外部工具
- **自定义Tool扩展**：通过注册自定义Tool实现金融场景能力（图谱查询、行情查询等）

## Agent 架构总览

```
                    ┌─────────────────────────┐
                    │  Orchestrator Agent     │ ← Supervisor（DeerFlow内置）
                    │  任务分解 → 分配 → 汇总  │
                    └──────────┬──────────────┘
                               │ 分发任务
          ┌────────────────────┼────────────────────┐
          │                    │                    │
┌─────────▼────────┐ ┌────────▼────────┐ ┌────────▼────────┐
│ Signal Scanner   │ │ Chain Analyst   │ │ Risk Monitor    │
│ (Worker)         │ │ (Worker)        │ │ (Worker)        │
└─────────┬────────┘ └────────┬────────┘ └─────────────────┘
          │                    │
          │ 信号结果           │ 归因结果
          ▼                    ▼
┌──────────────────┐ ┌──────────────────┐
│ Stock Screener   │ │ Report Writer    │
│ (Worker)         │ │ (Worker)         │
└──────────────────┘ └──────────────────┘
```

---

## 1. Orchestrator Agent（Supervisor — 编排调度）

### 职责
- 接收定时触发或用户指令，决定启动哪些分析任务
- 协调各子Agent的执行顺序和数据流转
- 汇总最终结果，决定输出方式（Alert/周报/深度研报）

### 触发条件
| 触发类型 | 频率 | 启动的子Agent |
|----------|------|--------------|
| 每日扫描 | 每交易日18:00 | Signal Scanner → (条件触发) Chain Analyst → Report Writer |
| 每周分析 | 每周六10:00 | Signal Scanner → Chain Analyst → Stock Screener → Report Writer |
| 深度研究 | 用户手动触发 | Chain Analyst → Stock Screener → Report Writer |
| 风险预警 | 实时 | Risk Monitor |

### 工具集
- `get_schedule_config()`: 获取调度配置
- `dispatch_agent(agent_name, params)`: 调度子Agent
- `aggregate_results(results)`: 汇总子Agent结果
- `route_output(content, level)`: 根据级别路由输出渠道

### 输入
- 定时事件 / 用户指令（如 "分析光通信产业链"）

### 输出
- 调度计划和最终汇总结果（传递给通知系统）

### 决策逻辑
```python
def orchestrate_daily():
    # Step 1: 信号扫描
    scan_results = dispatch_agent("signal_scanner", scope="all_chains")
    
    # Step 2: 筛选评分变化显著的产业链
    significant_chains = [r for r in scan_results if r.score_delta > 10]
    
    # Step 3: 对显著变化的链条做归因
    if significant_chains:
        for chain in significant_chains:
            analysis = dispatch_agent("chain_analyst", chain_id=chain.id)
            
            # Step 4: 生成Alert
            dispatch_agent("report_writer", 
                          type="alert", 
                          chain=chain, 
                          analysis=analysis)
```

---

## 2. Signal Scanner Agent（信号扫描Agent）

### 职责
- 调用信号检测引擎，扫描所有/指定产业链
- 计算各产业链的综合评分
- 检测评分变化，识别新增/消失的信号
- 输出结构化的信号扫描报告

### 工具集
- `scan_demand_inflection(chain_id)`: 检测需求拐点
- `scan_supply_shortage(chain_id)`: 检测供需紧张
- `scan_earnings_inflection(chain_id)`: 检测业绩拐点
- `scan_chip_concentration(chain_id)`: 检测筹码集中
- `scan_overseas_mapping(chain_id)`: 检测海外映射
- `scan_catalyst(chain_id)`: 检测催化剂
- `calculate_chain_score(signals)`: 计算综合评分
- `get_historical_scores(chain_id, days)`: 获取历史评分
- `query_knowledge_graph(chain_id)`: 查询产业链结构

### 输入
```json
{
  "scope": "all_chains" | "specific_chain",
  "chain_id": "optional_chain_id",
  "lookback_days": 7
}
```

### 输出
```json
{
  "scan_time": "2024-01-15T18:00:00",
  "results": [
    {
      "chain_id": "optical_communication",
      "chain_name": "光通信产业链",
      "current_score": 72,
      "previous_score": 58,
      "score_delta": +14,
      "triggered_signals": [
        {
          "type": "demand_inflection",
          "strength": 0.8,
          "detail": "中际旭创Q3营收同比+65%，连续3季度加速",
          "source": "financial_report",
          "trigger_date": "2024-01-10"
        }
      ],
      "new_signals_count": 2,
      "expired_signals_count": 1
    }
  ]
}
```

### Prompt模板
```
你是产业链信号扫描分析师。基于以下信号数据，判断各产业链的信号强度变化：

## 当前检测到的信号：
{signals_data}

## 历史评分：
{historical_scores}

请完成：
1. 对每条产业链评估信号的可靠性（数据源是否权威、信号是否可交叉验证）
2. 识别多信号共振的产业链（≥3类信号同时触发）
3. 标记可能的噪声信号（单一来源、无法验证的信号）
4. 输出按评分变化量排序的产业链列表
```

---

## 3. Chain Analyst Agent（产业链归因Agent）

### 职责
- 对评分显著变化的产业链，沿知识图谱做深度归因
- 分析驱动因素是短期波动还是结构性趋势
- 判断当前所处阶段（萌芽期/验证期/共识期/过热期）
- 追溯需求传导路径，识别弹性最大的环节

### 工具集
- `query_graph_upstream(node)`: 查询上游
- `query_graph_downstream(node)`: 查询下游
- `query_graph_path(from_node, to_node)`: 查询传导路径
- `get_segment_companies(segment_id)`: 获取环节内公司
- `get_company_financials(company_code)`: 获取公司财务数据
- `search_news_by_chain(chain_id, days)`: 搜索相关新闻
- `search_reports_by_chain(chain_id)`: 搜索相关研报
- `get_overseas_comparables(chain_id)`: 获取海外可比公司数据

### 输入
```json
{
  "chain_id": "optical_communication",
  "triggered_signals": [...],
  "score_delta": 14,
  "context": "评分从58升至72"
}
```

### 输出
```json
{
  "chain_id": "optical_communication",
  "analysis": {
    "driving_factors": "英伟达H200出货加速带动800G光模块需求...",
    "trend_type": "structural",  // structural | cyclical | event_driven
    "current_stage": "verification",  // seed | verification | consensus | overheated
    "stage_evidence": "下游订单已确认，但上游光芯片产能尚未释放...",
    "transmission_path": [
      {"from": "AI服务器需求", "to": "800G光模块", "status": "confirmed"},
      {"from": "800G光模块", "to": "光芯片", "status": "transmitting"},
      {"from": "光芯片", "to": "光芯片设备", "status": "not_yet"}
    ],
    "max_elasticity_segment": "光芯片",
    "elasticity_reason": "供给端产能有限，需求快速增长，量价齐升"
  }
}
```

### Prompt模板
```
你是一个资深产业链投资分析师。基于以下信号和知识图谱数据，完成深度归因分析：

## 产业链：{chain_name}
## 当前评分：{score}（变化：{score_delta}）
## 触发信号：
{signals_detail}

## 知识图谱上下游关系：
{kg_context}

## 相关新闻摘要：
{news_summary}

## 海外可比数据：
{overseas_data}

请完成：
1. 【核心驱动】是什么因素在驱动这条产业链？提供数据支撑。
2. 【趋势判断】这是短期事件驱动还是结构性趋势？为什么？
3. 【传导路径】需求如何从下游传导到上游？当前传导到了哪个环节？
4. 【阶段判断】当前处于萌芽期/验证期/共识期/过热期？判断依据是什么？
5. 【弹性分析】哪个环节弹性最大？为什么？

要求：结论先行，数据支撑，避免模糊表述。
```

---

## 4. Stock Screener Agent（标的筛选Agent）

### 职责
- 基于产业链归因结果，定位最受益的上市公司
- 叠加估值、财务质量、流动性等过滤条件
- 输出分层推荐列表（核心/卫星/观察）

### 工具集
- `get_chain_beneficiary_companies(chain_id, segment)`: 获取受益公司列表
- `get_company_valuation(code)`: 获取估值数据（PE/PB/PS）
- `get_company_financials(code)`: 获取财务指标
- `get_company_price_position(code)`: 获取价格位置（距高点/低点百分比）
- `get_institutional_holdings(code)`: 获取机构持仓变化
- `get_company_market_cap(code)`: 获取市值
- `compare_with_peers(code, peer_codes)`: 同行比较

### 筛选条件
```yaml
filters:
  # 必须条件
  must:
    - market_cap > 30亿  # 流动性保障
    - daily_volume_avg_20d > 5000万  # 可交易
    - not_st: true  # 排除ST
    - listed_days > 60  # 排除次新
    
  # 加分条件
  prefer:
    - pe_percentile < 70%  # 估值不在极端高位
    - revenue_growth_yoy > 0  # 营收正增长
    - gross_margin_trend: "improving"  # 毛利改善
    - institutional_increase: true  # 机构加仓
    
  # 减分条件
  penalize:
    - pe_percentile > 90%  # 估值过高
    - pledge_ratio > 50%  # 质押率过高
    - goodwill_ratio > 30%  # 商誉过高
```

### 输出
```json
{
  "chain_id": "optical_communication",
  "segment": "光芯片",
  "recommendations": {
    "core": [
      {
        "code": "688498",
        "name": "源杰科技",
        "logic": "国内CW激光器芯片龙头，直接受益800G硅光方案放量",
        "valuation": {"pe": 45, "pe_percentile": 35},
        "score": 85
      }
    ],
    "satellite": [...],
    "watchlist": [...]
  }
}
```

---

## 4.1 Stock Analysis Agent（对话式个股分析Agent）

### 职责
- 面向用户多轮对话，按问题自动执行候选股筛选、个股分析、个股对比或数据覆盖检查
- 只使用系统已入库的股票基础信息、K线、财报、信号和知识图谱数据
- 在LLM不可用时返回规则化分析结果，并明确标注数据缺口和低置信度原因
- 将每轮对话写入Agent执行日志，便于审计和复盘

### 工具封装策略
当前数据查询应封装为运行时Tool，而不是Codex skill：
- Tool适合Agent在每轮任务中动态查询业务数据，并返回结构化、可审计的结果
- skill适合开发期/操作期的工作流指导，不适合承载实时业务数据查询
- `StockDataTools`聚合候选股筛选、个股快照、个股对比、数据覆盖和股票搜索，避免Agent直接拼SQL

### 工具集
- `stock_data_tools.get_coverage()`: 查询股票、K线、财报、信号和候选池覆盖情况
- `stock_data_tools.screen_stocks(filters)`: 复用投研工作台评分筛选候选股
- `stock_data_tools.get_stock_snapshot(code)`: 查询单只股票基础信息、图谱暴露、K线指标、财报和近期信号
- `stock_data_tools.compare_stocks(codes)`: 对多只股票执行结构化对比
- `stock_data_tools.search_stocks(keyword)`: 按代码或名称检索股票

### 输入
```json
{
  "message": "光通信里筛低风险标的",
  "history": [
    {"role": "user", "content": "先看光通信"},
    {"role": "assistant", "content": "当前候选为..."}
  ],
  "filters": {
    "chain_name": "光通信产业链",
    "risk_tolerance": "low",
    "min_score": 60
  },
  "codes": ["300308", "300502"],
  "limit": 10
}
```

### 输出
```json
{
  "mode": "screen",
  "answer": "按当前真实入库数据筛选，靠前候选为...",
  "picks": [...],
  "snapshots": [],
  "data_gaps": ["候选池财报覆盖不足，基本面评分置信度偏低"],
  "confidence": "medium",
  "source_policy": "仅使用系统已入库的股票、K线、财报、信号和知识图谱数据；缺失数据必须标注，不得补造。"
}
```

---

## 5. Report Writer Agent（研报生成Agent）

### 职责
- 基于前序Agent的分析结果，生成不同类型的输出文档
- 支持三种输出：实时Alert、周度报告、深度研报

### 工具集
- `format_alert(data)`: 格式化Alert消息
- `format_weekly_report(data)`: 格式化周报
- `format_deep_research(data)`: 格式化深度研报
- `send_notification(channel, content)`: 发送通知

### 输出类型

#### Alert（实时触发）
```
🔴 产业链评分预警

【光通信产业链】评分从58→72（+14）
触发信号：产业需求拐点 + 海外映射
核心驱动：英伟达H200出货加速，800G光模块需求超预期
传导阶段：验证期（下游订单确认，上游产能紧张）
关注标的：源杰科技(688498)、长光华芯(688048)

详情请查看Dashboard
```

#### 周报
```markdown
# 产业链周度观察 (2024.01.08-01.14)

## 本周评分变化TOP3
| 产业链 | 本周 | 上周 | 变化 | 阶段 |
|--------|------|------|------|------|
| 光通信 | 72 | 58 | +14 | 验证期 |
| AI算力 | 68 | 65 | +3 | 共识期 |
| 半导体设备 | 45 | 48 | -3 | 观察期 |

## 重点产业链分析
### 光通信（评分72，验证期）
[归因分析内容...]

## 本周新增信号
[信号列表...]

## 推荐关注标的
[标的列表...]
```

#### 深度研报
结构化长文（2000-5000字），包含完整的归因、传导、阶段、标的、风险分析。

### Prompt模板
```
你是一位资深卖方分析师，请基于以下分析数据生成{report_type}：

## 分析数据：
{analysis_data}

## 输出要求：
- 结论先行，数据支撑
- 不使用模糊语言（"可能"、"也许"），用确定性程度量化表述
- 明确标注数据来源和时效性
- 风险提示要具体，指出什么指标变化会证伪当前逻辑
```

---

## 6. Risk Monitor Agent（风险监控Agent）

### 职责
- 持续监控已关注产业链的风险信号
- 检测信号证伪条件是否触发
- 监控推荐标的的负面变化
- 及时发出风险预警

### 工具集
- `get_active_recommendations()`: 获取当前有效推荐
- `check_falsification_conditions(chain_id)`: 检查证伪条件
- `get_negative_news(company_code)`: 获取负面新闻
- `check_price_drawdown(code, threshold)`: 检查回撤幅度
- `check_fundamental_deterioration(code)`: 检查基本面恶化
- `get_chain_score_trend(chain_id, days)`: 获取评分趋势

### 监控规则
```yaml
risk_rules:
  # 信号证伪
  signal_falsification:
    - condition: "下游营收增速连续2季度下滑"
      action: "降低需求拐点信号强度"
    - condition: "产品价格开始下跌"
      action: "降低供需紧张信号强度"
      
  # 标的风险
  stock_risk:
    - condition: "推荐后回撤 > 15%"
      action: "触发止损预警"
    - condition: "业绩预告大幅低于预期"
      action: "重新评估推荐逻辑"
    - condition: "核心客户流失/订单取消"
      action: "立即下调评级"
      
  # 产业链风险
  chain_risk:
    - condition: "评分连续3周下降"
      action: "将产业链标记为衰减"
    - condition: "政策风险事件"
      action: "紧急评估影响范围"
```

### 输出
```json
{
  "risk_alerts": [
    {
      "level": "warning",  // info | warning | critical
      "type": "signal_falsification",
      "chain_id": "optical_communication",
      "detail": "光芯片价格出现松动迹象，供需紧张信号可能减弱",
      "action_suggestion": "密切关注下月价格数据，暂不加仓",
      "affected_recommendations": ["688498", "688048"]
    }
  ]
}
```

---

## Agent 协作协议

### 数据流转格式
所有Agent之间通过JSON格式传递数据，统一schema：
```json
{
  "agent_id": "signal_scanner",
  "timestamp": "2024-01-15T18:05:00",
  "task_id": "daily_scan_20240115",
  "status": "completed",
  "result": { ... },
  "metadata": {
    "execution_time_ms": 3500,
    "llm_calls": 5,
    "tokens_used": 12000
  }
}
```

### 错误处理
- 单个Agent失败不应阻塞整体流程
- Orchestrator负责重试和降级策略
- 所有LLM调用配置超时和重试（max_retries=3, timeout=60s）
- 关键分析结果缓存，避免重复计算

### 成本控制
- 日常扫描使用低成本模型（GPT-4o-mini / Qwen-72B）
- 深度归因使用高性能模型（Claude 3.5 / GPT-4o）
- 每日/每周统计token消耗，超预算自动降级
- 相似查询结果缓存复用（TTL=4小时）

---

## ⚠️ 数据真实性保障

**所有Agent严格禁止以下行为：**
1. 使用模拟/虚构数据作为分析输入
2. 在缺失数据时自行编造填充
3. 将LLM的推测作为事实数据引用

**当数据缺失时：**
- Agent应明确标注"数据缺失"
- 在输出中标记置信度为"low"
- 通过Risk Monitor Agent提醒用户补充数据源
