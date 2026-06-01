---
name: overseas-healthcare-monitor
description: 监测海外头部医疗集团（东南亚、印度等）的最新动态。使用 Google News RSS 搜索目标机构的新闻、公告、财报等信息，汇总到飞书表格并生成 HTML 报告。触发词：海外医疗、IHH、Bumrungrad、康民医院、东南亚医疗集团、国际医院动态、医疗旅游。
---

# 海外医疗集团动态监测

监测海外头部医疗集团的最新动态，包括新闻、公告、财报、并购、扩张等信息。

## 目标机构（25 家）

### IHH Healthcare 集团（10 家）
- 新加坡：IHH Healthcare、Mount Elizabeth、Parkway East
- 马来西亚：Pantai、Gleneagles KL、SJMC、Island Hospital、Prince Court
- 印度：Fortis Healthcare
- 土耳其：Acibadem

### 泰国（8 家）
- Bumrungrad International (泰国 #1)
- Samitivej Hospitals (泰国 #2)
- Bangkok Hospital、MedPark (BDMS)
- Thonburi Hospital
- Praram 9 Hospital
- Phyathai Hospital Group

### 马来西亚其他（3 家）
- Sunway Medical Centre (马来西亚 #1)
- KPJ Healthcare
- Mahkota Medical Centre

### 新加坡其他（2 家）
- Raffles Medical Group
- Singapore General Hospital

### 印度其他（2 家）
- Apollo Hospitals (印度 #5)
- Aster DM Healthcare

## 快速开始

```bash
# 完整运行（搜索 + 飞书写入）
cd ~/.openclaw/workspace-agent2/skills/overseas-healthcare-monitor
python3 scripts/run.py

# 测试模式（不写入飞书）
python3 scripts/run.py --dry-run

# 生成 HTML 报告
python3 scripts/run.py --output html

# JSON + HTML
python3 scripts/run.py --output both
```

## 输出

1. **飞书表格** - 每条新闻记录
   - 表格：海外医院动态监测
   - Sheet：info
   - 字段：标题、机构、关键词、链接、摘要、日期、采集时间

2. **HTML 报告** - `data/parsed/YYYY-MM-DD/report.html`

3. **JSON 数据** - `data/parsed/YYYY-MM-DD/news.json`

## 配置文件

- `config/targets.json` - 目标机构清单（25 家）
- `config/feishu.json` - 飞书表格配置

## 飞书表格

- 表格链接：https://acnfpaaze45i.feishu.cn/wiki/JCUNw4PqwikZe4klnyuc95AhnRf
- spreadsheet_token: `CTnpsgOI4h5DmztzKIRcbW3Znc8`
- info sheet_id: `0wzUzh`

## 定时任务

建议每日运行一次（每天 09:00）：

```bash
python3 scripts/run.py
```

## 搜索策略

1. **机构关键词搜索** - 使用 Google News RSS 搜索每个机构的品牌名、医院名
2. **行业媒体** - Healthcare Asia、Hospital Management 等

## 搜索提供者

默认使用 **Google News RSS**（免费，无需 API key）：
- URL 格式：`https://news.google.com/rss/search?q=关键词`
- 需要代理访问（端口 7890）
- 备选：Tavily API、Firecrawl

## 注意事项

- Google News RSS 需要代理访问
- 新闻去重基于 URL
- 时区使用 Asia/Shanghai
