#!/usr/bin/env python3
"""海外医疗集团动态监测 - 主运行脚本

用法:
    python3 run.py                     # 完整运行
    python3 run.py --dry-run           # 测试模式，不写入飞书
    python3 run.py --output html       # 生成 HTML 页面
"""

import os
import json
import subprocess
import requests
import argparse
from datetime import datetime
from pathlib import Path

SCRIPT_DIR = Path(__file__).parent
SKILL_DIR = SCRIPT_DIR.parent
CONFIG_DIR = SKILL_DIR / "config"
DATA_DIR = SKILL_DIR / "data"

# 飞书配置
FEISHU_CONFIG = json.load(open(CONFIG_DIR / "feishu.json")) if (CONFIG_DIR / "feishu.json").exists() else {}

# Tavily API Key
TAVILY_API_KEY = os.environ.get("TAVILY_API_KEY", "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")

# 代理配置（用于访问 Google）
PROXY_HOST = os.environ.get("HTTPS_PROXY") or os.environ.get("https_proxy") or "http://127.0.0.1:7890"


def run_google_rss_search(query, limit=10):
    """使用 Google News RSS 搜索新闻（免费，无需 API key）"""
    import xml.etree.ElementTree as ET
    from urllib.parse import quote
    
    # 构建 RSS URL
    encoded_query = quote(query)
    rss_url = f"https://news.google.com/rss/search?q={encoded_query}&hl=en&gl=US&ceid=US:en"
    
    # 设置代理
    proxies = {
        "http": PROXY_HOST,
        "https": PROXY_HOST
    }
    
    try:
        response = requests.get(
            rss_url,
            proxies=proxies,
            timeout=15,
            headers={"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36"}
        )
        
        if response.status_code != 200:
            print(f"   ⚠️ Google RSS 搜索失败: {response.status_code}")
            return []
        
        # 解析 RSS XML
        root = ET.fromstring(response.content)
        items = root.findall(".//item")
        
        news = []
        for item in items[:limit]:
            title_elem = item.find("title")
            link_elem = item.find("link")
            pubDate_elem = item.find("pubDate")
            desc_elem = item.find("description")
            source_elem = item.find("source")
            
            # 提取内容
            title = title_elem.text if title_elem is not None else ""
            link = link_elem.text if link_elem is not None else ""
            pub_date = pubDate_elem.text if pubDate_elem is not None else ""
            description = desc_elem.text if desc_elem is not None else ""
            source = source_elem.text if source_elem is not None else ""
            
            # 清理标题（Google RSS 格式: "标题 - 来源"）
            if " - " in title and source:
                title = title.rsplit(" - ", 1)[0]
            
            news.append({
                "title": title,
                "url": link,
                "snippet": description,
                "description": description,
                "date": pub_date,
                "source": source,
                "imageUrl": ""
            })
        
        return news
        
    except Exception as e:
        print(f"   ⚠️ Google RSS 搜索异常: {e}")
        return []


def run_tavily_search(query, time_range="1d", limit=10):
    """使用 Tavily 搜索新闻"""
    try:
        response = requests.post(
            "https://api.tavily.com/search",
            json={
                "api_key": TAVILY_API_KEY,
                "query": query,
                "search_depth": "basic",
                "include_raw_content": False,
                "include_images": True,
                "max_results": limit
            },
            timeout=30
        )
        
        if response.status_code == 200:
            data = response.json()
            results = data.get("results", [])
            
            # 转换为统一格式
            news = []
            for item in results:
                news.append({
                    "title": item.get("title", ""),
                    "url": item.get("url", ""),
                    "snippet": item.get("content", ""),
                    "description": item.get("content", ""),
                    "date": item.get("published_date", ""),
                    "imageUrl": item.get("images", [""])[0] if item.get("images") else ""
                })
            return news
        else:
            print(f"   ⚠️ Tavily 搜索失败: {response.status_code}")
    except Exception as e:
        print(f"   ⚠️ Tavily 搜索异常: {e}")
    return []


def run_firecrawl_search(query, time_range="1d", limit=10):
    """使用 Firecrawl 搜索新闻"""
    output_file = DATA_DIR / "raw" / f"search_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
    output_file.parent.mkdir(parents=True, exist_ok=True)
    
    cmd = [
        "firecrawl", "search", query,
        "--sources", "news",
        "--limit", str(limit),
        "-o", str(output_file),
        "--json"
    ]
    
    # 添加时间过滤
    if time_range:
        cmd.extend(["--tbs", f"qdr:{time_range}"])
    
    env = {**os.environ, "NODE_EXTRA_CA_CERTS": "/etc/ssl/cert.pem"}
    
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=60, env=env)
        if result.returncode == 0 and output_file.exists():
            data = json.load(open(output_file))
            return data.get("data", {}).get("news", [])
    except Exception as e:
        print(f"   ⚠️ 搜索失败: {e}")
    return []


def run_search(query, time_range="1d", limit=10, provider="firecrawl"):
    """统一搜索接口，支持切换搜索提供者
    
    provider 选项:
    - firecrawl (默认): Firecrawl 搜索，需 API key
    - google_rss: Google News RSS，免费无限制，需代理
    - tavily: Tavily API，需 API key
    """
    if provider == "google_rss":
        return run_google_rss_search(query, limit)
    elif provider == "tavily":
        return run_tavily_search(query, time_range, limit)
    else:
        return run_firecrawl_search(query, time_range, limit)


def search_entity_news(entity, config):
    """搜索单个机构的新闻"""
    results = []
    keywords = entity.get("keywords", [])
    name = entity.get("name", "")
    provider = config.get("search_provider", "tavily")
    
    for keyword in keywords:
        print(f"     搜索: {keyword}")
        news = run_search(
            keyword,
            time_range=config.get("default_time_range", "1d"),
            limit=config.get("max_results_per_entity", 10),
            provider=provider
        )
        
        for item in news:
            item["entity_name"] = name
            item["keyword"] = keyword
            results.append(item)
    
    return results


def search_news_sources(source, config):
    """搜索行业新闻源"""
    results = []
    keywords = source.get("keywords", [])
    name = source.get("name", "")
    provider = config.get("search_provider", "tavily")
    
    for keyword in keywords:
        query = f"{keyword} site:{source.get('url', '')}"
        print(f"     搜索源: {name} - {keyword}")
        news = run_search(
            query,
            time_range=config.get("default_time_range", "1d"),
            limit=config.get("max_results_per_source", 5),
            provider=provider
        )
        
        for item in news:
            item["source_name"] = name
            results.append(item)
    
    return results


def search_sea_health_news(config):
    """搜索东南亚卫生健康动态"""
    results = []
    sea_config = config.get("sea_health_news", {})
    countries = sea_config.get("countries", [])
    keywords = sea_config.get("keywords", [])
    provider = config.get("search_provider", "tavily")
    
    for country in countries:
        country_name = country.get("name", "")
        sites = country.get("search_sites", [])
        
        # 为每个国家的权威站点搜索（减少搜索量）
        for site in sites[:1]:  # 每个国家限制1个站点
            for keyword in keywords[:2]:  # 每个站点限制2个关键词
                query = f"{keyword} site:{site}"
                print(f"     🌏 东南亚动态: {country_name} - {keyword}")
                try:
                    news = run_search(
                        query,
                        time_range=config.get("default_time_range", "1d"),
                        limit=3,
                        provider=provider
                    )
                    
                    for item in news:
                        item["sea_country"] = country_name
                        item["news_type"] = "sea_health"
                        results.append(item)
                except Exception as e:
                    print(f"     ⚠️ 搜索失败: {e}")
                    continue
    
    return results


def validate_url(url, timeout=5):
    """验证链接是否可访问，返回 (is_valid, status_code)"""
    if not url:
        return False, None
    try:
        resp = requests.head(url, timeout=timeout, allow_redirects=True, 
                           headers={'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'})
        status = resp.status_code
        # 200-299 有效，403 可能是反爬虫（浏览器可访问）
        if 200 <= status < 300:
            return True, status
        elif status == 403:
            return True, status  # 保留但标注
        elif status in [404, 410, 500, 502, 503]:
            return False, status
        else:
            return True, status  # 其他状态保留
    except Exception:
        return False, None


def deduplicate_news(all_news, validate_links=False):
    """去重，可选验证链接有效性"""
    seen_urls = set()
    unique = []
    invalid_count = 0
    
    for item in all_news:
        url = item.get("url", "")
        if url and url not in seen_urls:
            if validate_links:
                is_valid, status = validate_url(url)
                if not is_valid:
                    invalid_count += 1
                    continue
                item["status_code"] = status
            seen_urls.add(url)
            unique.append(item)
    
    if validate_links and invalid_count > 0:
        print(f"   🔗 过滤无效链接: {invalid_count} 条")
    
    return unique


def save_to_feishu(news_items, config):
    """保存到飞书电子表格"""
    if not FEISHU_CONFIG:
        print("   ⚠️ 飞书配置不存在，跳过写入")
        return False
    
    # 获取 access token
    resp = requests.post(
        "https://open.feishu.cn/open-apis/auth/v3/tenant_access_token/internal",
        json={
            "app_id": FEISHU_CONFIG.get("app_id"),
            "app_secret": FEISHU_CONFIG.get("app_secret")
        },
        timeout=10
    )
    token = resp.json().get("tenant_access_token")
    if not token:
        print("   ⚠️ 获取飞书 token 失败")
        return False
    
    spreadsheet_token = FEISHU_CONFIG.get("spreadsheet_token")
    sheet_id = FEISHU_CONFIG.get("sheets", {}).get("info")
    
    if not spreadsheet_token or not sheet_id:
        print("   ⚠️ 飞书表格配置不完整")
        return False
    
    # 准备数据（二维数组）
    rows = []
    # 表头
    rows.append(["标题", "机构", "关键词", "链接", "摘要", "日期", "采集时间"])
    # 数据行
    for item in news_items:
        rows.append([
            item.get("title", "")[:200],  # 标题
            item.get("entity_name", ""),   # 机构
            item.get("keyword", ""),       # 关键词
            item.get("url", ""),           # 链接
            item.get("snippet", item.get("description", ""))[:500],  # 摘要
            item.get("date", ""),          # 日期
            datetime.now().strftime("%Y-%m-%d %H:%M:%S")  # 采集时间
        ])
    
    # 写入数据到 info sheet
    # 先清空现有数据，再写入新数据
    range_str = f"{sheet_id}!A1:G{len(rows)}"
    
    resp = requests.put(
        f"https://open.feishu.cn/open-apis/sheets/v2/spreadsheets/{spreadsheet_token}/values",
        headers={
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json"
        },
        json={
            "valueRange": {
                "range": range_str,
                "values": rows
            }
        },
        timeout=30
    )
    
    if resp.status_code == 200 and resp.json().get("code") == 0:
        print(f"   ✅ 写入 {len(news_items)} 条新闻到飞书表格")
        return True
    else:
        print(f"   ⚠️ 写入失败: {resp.text}")
        return False


def translate_text(text, target_lang="zh"):
    """翻译文本（使用远程 vLLM 服务 - qwen3-fast）"""
    if not text:
        return text
    
    # 检查是否已经是中文
    if any('\u4e00' <= c <= '\u9fff' for c in text):
        return text
    
    try:
        import re
        
        response = requests.post(
            "http://47.117.187.203/v1/chat/completions",
            headers={
                "Authorization": "Bearer appkey-1-9dd5567f93ab49cb828424ebec086ff9",
                "Content-Type": "application/json"
            },
            json={
                "model": "qwen3-fast",
                "messages": [
                    {"role": "user", "content": f"Translate to Chinese, output ONLY Chinese: {text}"}
                ],
                "max_tokens": 1500,
                "temperature": 0.1
            },
            timeout=60
        )
        
        if response.status_code != 200:
            return text
        
        result = response.json()["choices"][0]["message"]["content"]
        
        # 去除 <think/> 标签内的推理内容
        cleaned = re.sub(r'<think.*?>.*?</think\s*>', '', result, flags=re.DOTALL)
        cleaned = cleaned.strip()
        
        # 如果清理后包含中文，返回清理后的结果
        if any('\u4e00' <= c <= '\u9fff' for c in cleaned):
            return cleaned
        
        return text
    except Exception as e:
        # 翻译失败时返回原文
        return text


def summarize_text(text, max_length=100, title=""):
    """生成简洁摘要（使用 AI 总结）"""
    if not text and not title:
        return ""
    
    # 合并标题和内容作为输入
    input_text = f"{title}\n\n{text}" if title else text
    
    # 截取输入长度
    input_text = input_text[:500] if len(input_text) > 500 else input_text
    
    try:
        import re
        response = requests.post(
            "http://47.117.187.203/v1/chat/completions",
            headers={
                "Authorization": "Bearer appkey-1-9dd5567f93ab49cb828424ebec086ff9",
                "Content-Type": "application/json"
            },
            json={
                "model": "qwen3-fast",
                "messages": [
                    {"role": "user", "content": f"/no_think\n用1-2句话总结新闻核心内容，中文回答，不超过60字：\n{input_text}"}
                ],
                "max_tokens": 100,
                "temperature": 0.1
            },
            timeout=30
        )
        
        if response.status_code == 200:
            result = response.json()["choices"][0]["message"]["content"]
            # 去除 <think/> 标签内的推理内容
            cleaned = re.sub(r'<think[^>]*>.*?</think\s*>', '', result, flags=re.DOTALL | re.IGNORECASE)
            # 去除可能的 /no_think 输出
            cleaned = re.sub(r'/no_think', '', cleaned)
            cleaned = cleaned.strip()
            
            # 检查是否是有效的中文摘要
            if cleaned and len(cleaned) > 5 and any('\u4e00' <= c <= '\u9fff' for c in cleaned):
                return cleaned[:max_length + 20]
    except Exception as e:
        pass
    
    # AI 失败时，简单截取原文
    if text:
        return text[:max_length] + "..." if len(text) > max_length else text
    return ""


# 机构分类
# 格式: "机构名": ("分类", "集团")
# 分类: IHH集团 / 新加坡 / 马来西亚 / 泰国 / 印度 / 土耳其
# 集团: 所属集团，独立机构为 None

ENTITY_INFO = {
    # ===== IHH集团总部 =====
    "IHH Healthcare": ("IHH集团", "IHH Healthcare"),  # 总部
    
    # ===== 新加坡 =====
    "Mount Elizabeth Hospital": ("新加坡", "IHH Healthcare"),
    "Parkway East Hospital": ("新加坡", "IHH Healthcare"),
    "Raffles Medical Group": ("新加坡", None),
    "Singapore General Hospital": ("新加坡", None),
    
    # ===== 马来西亚 =====
    "Pantai Hospitals": ("马来西亚", "IHH Healthcare"),
    "Gleneagles Kuala Lumpur": ("马来西亚", "IHH Healthcare"),
    "Subang Jaya Medical Centre": ("马来西亚", "IHH Healthcare"),
    "Island Hospital": ("马来西亚", "IHH Healthcare"),
    "Prince Court Medical Centre": ("马来西亚", "IHH Healthcare"),
    "Sunway Medical Centre": ("马来西亚", "Sunway Healthcare"),
    "KPJ Healthcare": ("马来西亚", "KPJ"),
    "Mahkota Medical Centre": ("马来西亚", "HMI Medical"),
    
    # ===== 泰国 =====
    "Bumrungrad International Hospital": ("泰国", None),
    "Samitivej Hospitals": ("泰国", None),
    "Bangkok Hospital Group": ("泰国", "BDMS"),
    "MedPark Hospital": ("泰国", "BDMS"),
    "BDMS (Bangkok Dusit Medical Services)": ("泰国", "BDMS"),  # 总部
    "Thonburi Hospital": ("泰国", "Thonburi Healthcare Group"),
    "Praram 9 Hospital": ("泰国", None),
    "Phyathai Hospital Group": ("泰国", "Phyathai-Paolo Group"),
    
    # ===== 印度 =====
    "Fortis Healthcare": ("印度", "IHH Healthcare"),
    "Apollo Hospitals": ("印度", "Apollo"),
    "Aster DM Healthcare": ("印度", "Aster"),
    
    # ===== 土耳其 =====
    "Acibadem Healthcare Group": ("土耳其", "IHH Healthcare"),
}

# 简化版：只获取分类
ENTITY_LOCATION = {name: info[0] for name, info in ENTITY_INFO.items()}

# 获取所属集团
def get_entity_group(entity_name):
    """获取机构所属集团"""
    if entity_name in ENTITY_INFO:
        return ENTITY_INFO[entity_name][1]
    return None

# 分类排序
LOCATION_ORDER = ["IHH集团", "新加坡", "马来西亚", "泰国", "印度", "土耳其", "其他"]

# 东南亚国家排序
SEA_COUNTRIES = ["新加坡", "马来西亚", "泰国", "印尼", "越南", "菲律宾", "印度", "其他"]


def get_location_for_entity(entity_name):
    """获取机构所在国家/地区"""
    return ENTITY_LOCATION.get(entity_name, "其他")


# 医疗集团层级定义（保留用于参考）
GROUP_HIERARCHY = {
    "IHH Healthcare": {
        "group_name": "IHH Healthcare",
        "entities": [
            "IHH Healthcare", "Mount Elizabeth Hospital", "Parkway East Hospital",
            "Pantai Hospitals", "Gleneagles Kuala Lumpur", "Subang Jaya Medical Centre",
            "Island Hospital", "Prince Court Medical Centre", "Fortis Healthcare",
            "Acibadem Healthcare Group"
        ]
    },
    "BDMS": {
        "group_name": "BDMS (Bangkok Dusit Medical Services)",
        "entities": ["Bangkok Hospital Group", "MedPark Hospital", "BDMS (Bangkok Dusit Medical Services)"]
    },
    "Thonburi Healthcare Group": {
        "group_name": "Thonburi Healthcare Group",
        "entities": ["Thonburi Hospital"]
    },
    "Phyathai-Paolo Hospital Group": {
        "group_name": "Phyathai-Paolo Hospital Group",
        "entities": ["Phyathai Hospital Group"]
    },
    "Sunway Healthcare Group": {
        "group_name": "Sunway Healthcare Group",
        "entities": ["Sunway Medical Centre"]
    },
    "KPJ Healthcare": {
        "group_name": "KPJ Healthcare",
        "entities": ["KPJ Healthcare"]
    },
    "HMI Medical": {
        "group_name": "HMI Medical",
        "entities": ["Mahkota Medical Centre"]
    },
    "Raffles Medical Group": {
        "group_name": "Raffles Medical Group",
        "entities": ["Raffles Medical Group"]
    },
    "Apollo Hospitals": {
        "group_name": "Apollo Hospitals",
        "entities": ["Apollo Hospitals"]
    },
    "Aster DM Healthcare": {
        "group_name": "Aster DM Healthcare",
        "entities": ["Aster DM Healthcare"]
    },
    "独立机构": {
        "group_name": "独立机构",
        "entities": ["Bumrungrad International Hospital", "Samitivej Hospitals", "Praram 9 Hospital", "Singapore General Hospital"]
    }
}


def get_group_for_entity(entity_name):
    """根据机构名获取所属集团"""
    for group_key, group_data in GROUP_HIERARCHY.items():
        if entity_name in group_data["entities"]:
            return group_key, group_data["group_name"]
    return "其他", "其他机构"


def is_healthcare_industry_news(item):
    """判断新闻是否与医疗机构行业动向相关
    
    相关类别：
    1. 扩张动态：新建医院、进入新市场、海外布局、开设新院区
    2. 资本动态：收购、合并、融资、IPO、股权变动
    3. 合作动态：战略合作、签约、联盟、MOU、政府合作
    4. 产品服务动态：新技术引进、AI落地、新科室、新设备、数字化转型
    5. 人事动态：CEO变动、高管任命、管理层调整
    6. 政策响应：监管变化、医保接入、政策合规
    
    过滤掉：事故、犯罪、个人新闻、节日活动等
    """
    title = item.get("title", "").lower()
    snippet = item.get("snippet", "") or item.get("summary", "") or ""
    content = f"{title} {snippet.lower()}"
    
    # === 过滤关键词（不相关内容）===
    filter_keywords = [
        # 个人新闻
        "baby", "babies", "birth", "born", "pregnant", "pregnancy", "mother", "father", "parents",
        "wedding", "marriage", "divorce", "family", "child", "children",
        # 节日活动
        "eid", "festival", "celebration", "holiday", "christmas", "new year", "ramadan",
        # 事故犯罪
        "accident", "crash", "crime", "murder", "theft", "fraud", "scandal", "lawsuit", "sue", "sued",
        "death", "died", "killed", "victim", "injured", "injury",
        # 娱乐体育
        "sport", "football", "cricket", "movie", "celebrity", "actor", "singer",
        # 普通医疗（非行业动态）
        "patient story", "patient shares", "miracle", "survivor", "recovery story",
    ]
    
    # === 过滤无效标题（网站导航页、归档页等）===
    invalid_title_patterns = [
        "archives", "archive", "| page", "page 1", "page 2", "page 3", "page 4",
        "category", "tag:", "home |", "about |", "contact |",
        "vision and mission", "history", "profile",
    ]
    
    for pattern in invalid_title_patterns:
        if pattern in title:
            return False
    
    # 如果包含过滤关键词，直接排除
    for kw in filter_keywords:
        if kw in content:
            return False
    
    # === 相关关键词（行业动态）===
    relevant_keywords = [
        # 1. 扩张动态
        "new hospital", "open hospital", "launch hospital", "expand", "expansion", "new branch",
        "new centre", "new center", "new clinic", "new facility", "new campus",
        "enter market", "new market", "overseas", "international expansion", "global expansion",
        "construction", "break ground", "ribbon cutting", "grand opening",
        
        # 2. 资本动态
        "acquisition", "acquire", "merger", "merge", "acquired by", "buys", "sold",
        "ipo", "public offering", "listing", "listed", "go public",
        "funding", "investment", "invest", "raise", "raised", "funding round",
        "stake", "equity", "shareholder", "shares", "valuation",
        "private equity", "buyout",
        
        # 3. 合作动态
        "partnership", "partner", "collaborate", "collaboration", "alliance", "strategic",
        "sign", "signed", "agreement", "contract", "deal", "mou", "memorandum",
        "joint venture", "joint project", "government partnership", "ministry of health",
        
        # 4. 产品服务动态
        "new technology", "ai", "artificial intelligence", "machine learning", "digital",
        "robot", "robotic", "new equipment", "new device", "new machine",
        "new department", "new ward", "new service", "launch service", "new specialty",
        "telehealth", "telemedicine", "digital transformation", "smart hospital",
        "innovation", "innovative", "cutting-edge", "state-of-the-art",
        
        # 5. 人事动态
        "ceo", "chief executive", "appointed", "appointment", "new head", "new chief",
        "executive", "management", "director", "board", "resign", "resignation", "step down",
        "promoted", "leadership", "top management",
        
        # 6. 政策响应
        "regulation", "regulatory", "compliance", "policy", "government", "ministry",
        "insurance", "medicare", "medicaid", "health insurance", "reimbursement",
        "license", "licensing", "accreditation", "certification", "approved", "approval",
    ]
    
    # 检查是否包含相关关键词
    relevant_count = 0
    for kw in relevant_keywords:
        if kw in content:
            relevant_count += 1
    
    # 至少包含1个相关关键词才算相关
    return relevant_count >= 1


def parse_relative_date(date_str):
    """解析相对日期，返回距今天数，无法解析返回 None"""
    if not date_str:
        return None
    
    date_lower = date_str.lower().strip()
    
    # "X hours ago", "X minutes ago", "just now" → 当天
    if "hour" in date_lower or "minute" in date_lower or "just now" in date_lower:
        return 0
    
    # "today" → 当天
    if date_lower == "today":
        return 0
    
    # "yesterday" → 1天前
    if date_lower == "yesterday":
        return 1
    
    # "X day ago" 或 "X days ago"
    if "day" in date_lower:
        import re
        match = re.search(r'(\d+)\s*day', date_lower)
        if match:
            return int(match.group(1))
        # "a day ago" 或 "1 day ago"
        match = re.search(r'(\d+|a)\s*day', date_lower)
        if match:
            return 1 if match.group(1) == 'a' else int(match.group(1))
    
    # "X week ago" 或 "X weeks ago" → 返回大数字表示很旧
    if "week" in date_lower:
        import re
        match = re.search(r'(\d+)\s*week', date_lower)
        if match:
            return int(match.group(1)) * 7  # 转换成天数
    
    # "X month ago" 或 "X months ago" → 返回大数字
    if "month" in date_lower:
        import re
        match = re.search(r'(\d+)\s*month', date_lower)
        if match:
            return int(match.group(1)) * 30
    
    # "X year ago" → 返回大数字
    if "year" in date_lower:
        return 365
    
    # 尝试解析具体日期格式
    try:
        from datetime import datetime
        # 尝试多种格式
        for fmt in [
            "%a, %d %b %Y %H:%M:%S %Z",  # RFC 2822: "Sat, 30 May 2026 00:41:00 GMT"
            "%a, %d %b %Y %H:%M:%S",      # 无时区
            "%b %d, %Y",                   # "May 15, 2026"
            "%B %d, %Y",                   # "May 15, 2026"
            "%Y-%m-%d",                    # "2026-05-15"
            "%d/%m/%Y",                    # "15/05/2026"
            "%m/%d/%Y"                     # "05/15/2026"
        ]:
            try:
                parsed = datetime.strptime(date_str.strip(), fmt)
                days_diff = (datetime.now() - parsed).days
                return days_diff
            except:
                continue
    except:
        pass
    
    return None  # 无法解析


def load_existing_news():
    """加载已有的新闻数据（从最新的日期目录）"""
    parsed_dir = DATA_DIR / "parsed"
    if not parsed_dir.exists():
        return [], []
    
    # 获取所有日期目录，按日期排序
    date_dirs = sorted([d for d in parsed_dir.iterdir() if d.is_dir()], reverse=True)
    
    for date_dir in date_dirs:
        news_file = date_dir / "news.json"
        if news_file.exists():
            try:
                data = json.load(open(news_file))
                institutions = data.get("institutions", [])
                sea_health = data.get("sea_health", [])
                print(f"   📂 加载历史数据: {date_dir.name} ({len(institutions)} 条机构新闻, {len(sea_health)} 条东南亚动态)")
                return institutions, sea_health
            except:
                continue
    
    return [], []


def merge_and_cleanup_news(existing_news, new_news, max_days=7):
    """合并新旧新闻，删除超过指定天数的旧数据"""
    from datetime import datetime, timedelta
    
    cutoff_date = datetime.now() - timedelta(days=max_days)
    print(f"   🗑️ 清理 {max_days} 天前的旧数据...")
    
    # 合并所有新闻
    all_news = existing_news + new_news
    
    # 去重（基于 URL）
    seen_urls = set()
    unique_news = []
    removed_old = 0
    
    for item in all_news:
        url = item.get("url", "")
        if url and url not in seen_urls:
            # 检查日期是否过期
            date_str = item.get("date", "")
            days_ago = parse_relative_date(date_str)
            
            # 保留无法解析日期或日期在范围内的新闻
            if days_ago is None or days_ago <= max_days:
                seen_urls.add(url)
                unique_news.append(item)
            else:
                removed_old += 1
    
    if removed_old > 0:
        print(f"   🗑️ 删除 {removed_old} 条过期新闻")
    
    return unique_news


def calculate_similarity(title1, title2):
    """计算两个标题的相似度（0-1）"""
    from difflib import SequenceMatcher
    
    # 标准化：转小写，去掉多余空格
    t1 = title1.lower().strip()
    t2 = title2.lower().strip()
    
    # 完全一样
    if t1 == t2:
        return 1.0
    
    # 使用 SequenceMatcher 计算相似度
    return SequenceMatcher(None, t1, t2).ratio()


def deduplicate_by_similarity(news_items, threshold=0.8):
    """按标题相似度去重
    
    Args:
        news_items: 新闻列表
        threshold: 相似度阈值，超过此值视为重复
    
    Returns:
        去重后的新闻列表
    """
    if not news_items:
        return []
    
    unique = []
    
    for item in news_items:
        title = item.get("title", "")
        is_duplicate = False
        
        # 与已保留的新闻比较
        for existing in unique:
            existing_title = existing.get("title", "")
            similarity = calculate_similarity(title, existing_title)
            
            if similarity >= threshold:
                is_duplicate = True
                break
        
        if not is_duplicate:
            unique.append(item)
    
    return unique


def generate_html(news_items, output_path, sea_news=None):
    """生成 HTML 页面"""
    print("\n📝 生成 HTML 报告...")
    
    # 先进行过滤和去重
    # 过滤掉 entity_name 为 None 的新闻
    news_items = [item for item in news_items if item.get("entity_name")]
    
    # 过滤掉 moomoo 证券来源（只有标题无内容）
    news_items = [item for item in news_items if 'moomoo' not in item.get("url", "").lower()]
    
    # 过滤掉与医疗行业动向无关的新闻
    before_filter = len(news_items)
    news_items = [item for item in news_items if is_healthcare_industry_news(item)]
    print(f"   🔍 有效机构新闻: {len(news_items)} 条（过滤 {before_filter - len(news_items)} 条无关内容）")
    
    # 按标题相似度去重（同一机构内比较）
    by_entity = {}
    for item in news_items:
        entity = item.get("entity_name", "其他")
        if entity not in by_entity:
            by_entity[entity] = []
        by_entity[entity].append(item)
    
    unique_news = []
    for entity, items in by_entity.items():
        unique_items = deduplicate_by_similarity(items, threshold=0.8)
        unique_news.extend(unique_items)
    
    print(f"   🔄 去重后: {len(unique_news)} 条（移除 {len(news_items) - len(unique_news)} 条相似重复）")
    
    # 按时间分类（包含关系：近3天包含今天，近1周包含近3天）
    today_news = []
    last3days_news = []  # 近3天（含今天）
    lastweek_news = []   # 近1周（含今天）
    
    for item in unique_news:
        date_str = item.get("date", "")
        days_ago = parse_relative_date(date_str)
        
        # 只保留 7 天内的新闻
        if days_ago is not None and days_ago <= 7:
            lastweek_news.append(item)  # 近1周包含所有7天内的
            
            if days_ago <= 3:
                last3days_news.append(item)  # 近3天（含今天）
                
                if days_ago == 0:
                    today_news.append(item)  # 只有今天
    
    print(f"   📅 今天: {len(today_news)} 条 | 近3天: {len(last3days_news)} 条 | 近1周: {len(lastweek_news)} 条")
    
    # 处理东南亚卫生动态
    def filter_sea_news_by_time(sea_list):
        """按时间段过滤东南亚动态"""
        today, last3days, lastweek = [], [], []
        for item in sea_list:
            date_str = item.get("date", "")
            days_ago = parse_relative_date(date_str)
            if days_ago is not None and days_ago <= 7:
                lastweek.append(item)
                if days_ago <= 3:
                    last3days.append(item)
                    if days_ago == 0:
                        today.append(item)
        return today, last3days, lastweek
    
    def group_sea_news_by_country(sea_list):
        """按国家分组东南亚动态"""
        grouped = {}
        for item in sea_list:
            country = item.get("sea_country", "其他")
            if country not in grouped:
                grouped[country] = []
            grouped[country].append(item)
        return grouped
    
    sea_today, sea_3days, sea_week = [], [], []
    sea_grouped_today, sea_grouped_3days, sea_grouped_week = {}, {}, {}
    if sea_news:
        sea_today, sea_3days, sea_week = filter_sea_news_by_time(sea_news)
        sea_grouped_today = group_sea_news_by_country(sea_today)
        sea_grouped_3days = group_sea_news_by_country(sea_3days)
        sea_grouped_week = group_sea_news_by_country(sea_week)
        print(f"   🌏 东南亚动态 - 今天: {len(sea_today)} 条 | 近3天: {len(sea_3days)} 条 | 近1周: {len(sea_week)} 条")
    
    # 按国家/地区->机构层级分组
    def group_news_by_location(news_list):
        grouped = {}
        for item in news_list:
            entity = item.get("entity_name", "其他")
            location = get_location_for_entity(entity)
            
            if location not in grouped:
                grouped[location] = {
                    "location_name": location,
                    "entities": {}
                }
            
            if entity not in grouped[location]["entities"]:
                grouped[location]["entities"][entity] = []
            grouped[location]["entities"][entity].append(item)
        return grouped
    
    grouped_today = group_news_by_location(today_news)
    grouped_3days = group_news_by_location(last3days_news)
    grouped_week = group_news_by_location(lastweek_news)
    
    # 统计三个时间段的机构排行
    def get_entity_ranking(news_list):
        stats = {}
        for item in news_list:
            entity = item.get("entity_name", "其他")
            if entity not in stats:
                stats[entity] = 0
            stats[entity] += 1
        return sorted(stats.items(), key=lambda x: -x[1])
    
    today_entity_ranking = get_entity_ranking(today_news)
    last3days_entity_ranking = get_entity_ranking(last3days_news)
    lastweek_entity_ranking = get_entity_ranking(lastweek_news)
    
    today_active_entities = len(today_entity_ranking)
    last3days_active_entities = len(last3days_entity_ranking)
    lastweek_active_entities = len(lastweek_entity_ranking)
    
    # 生成 HTML
    html = f"""<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>海外医疗集团动态监测 - {datetime.now().strftime('%Y-%m-%d')}</title>
    <style>
        * {{ box-sizing: border-box; margin: 0; padding: 0; }}
        :root {{
            --primary: #003B83;
            --primary-light: #0052B8;
            --primary-lighter: #0066E6;
            --primary-dark: #002B61;
        }}
        body {{ 
            font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, 'PingFang SC', 'Microsoft YaHei', sans-serif; 
            max-width: 1400px; 
            margin: 0 auto; 
            padding: 20px; 
            background: #f5f7fa;
            min-height: 100vh;
        }}
        h1 {{ 
            background: linear-gradient(135deg, #002B61 0%, #003B83 100%);
            color: white;
            padding: 22px 28px;
            border-radius: 12px;
            margin-bottom: 20px;
            box-shadow: 0 4px 25px rgba(0, 59, 131, 0.5);
            font-size: 26px;
            border: 1px solid rgba(255,255,255,0.1);
        }}
        .summary {{ 
            background: rgba(255,255,255,0.95); 
            padding: 22px 28px; 
            border-radius: 12px; 
            margin-bottom: 25px; 
            box-shadow: 0 4px 20px rgba(0,0,0,0.1);
            border-left: 5px solid #003B83;
        }}
        .summary-title {{
            color: #003B83;
            font-size: 17px;
            font-weight: 600;
            margin-bottom: 12px;
        }}
        .summary-stats {{
            display: flex;
            gap: 35px;
            flex-wrap: wrap;
        }}
        .stat-item {{
            display: flex;
            align-items: center;
            gap: 10px;
        }}
        .stat-label {{
            color: #0052B8;
            font-size: 14px;
        }}
        .stat-value {{
            color: #003B83;
            font-size: 20px;
            font-weight: 700;
        }}
        
        /* 排行榜样式 */
        .ranking-section {{
            margin-top: 18px;
            padding-top: 18px;
            border-top: 1px solid #e3f2fd;
        }}
        .ranking-title {{
            color: #003B83;
            font-size: 15px;
            font-weight: 600;
            margin-bottom: 12px;
        }}
        .ranking-list {{
            display: flex;
            flex-direction: column;
            gap: 10px;
        }}
        .ranking-item {{
            display: flex;
            align-items: center;
            gap: 12px;
        }}
        .ranking-item .rank {{
            width: 24px;
            height: 24px;
            border-radius: 50%;
            background: linear-gradient(135deg, #003B83 0%, #0052B8 100%);
            color: white;
            display: flex;
            align-items: center;
            justify-content: center;
            font-size: 12px;
            font-weight: 600;
            flex-shrink: 0;
        }}
        .ranking-item .entity-name {{
            min-width: 180px;
            color: #37474f;
            font-size: 14px;
            font-weight: 500;
        }}
        .bar-container {{
            flex: 1;
            height: 8px;
            background: #e3f2fd;
            border-radius: 4px;
            overflow: hidden;
            max-width: 200px;
        }}
        .bar {{
            height: 100%;
            background: linear-gradient(90deg, #003B83 0%, #0066E6 100%);
            border-radius: 4px;
            transition: width 0.3s ease;
        }}
        .bar-count {{
            color: #003B83;
            font-size: 13px;
            font-weight: 600;
            min-width: 40px;
            text-align: right;
        }}
        .ranking-empty {{
            color: #90a4ae;
            font-size: 14px;
            padding: 12px 0;
        }}
        
        /* 标签页样式 */
        .tabs {{
            display: flex;
            gap: 8px;
            margin-bottom: 20px;
            background: white;
            padding: 8px;
            border-radius: 12px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
        }}
        .tab-btn {{
            flex: 1;
            padding: 14px 24px;
            border: none;
            background: transparent;
            color: #546e7a;
            font-size: 15px;
            font-weight: 500;
            cursor: pointer;
            border-radius: 8px;
            transition: all 0.2s ease;
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 8px;
        }}
        .tab-btn:hover {{
            background: #e3f2fd;
            color: #003B83;
        }}
        .tab-btn.active {{
            background: linear-gradient(135deg, #003B83 0%, #0052B8 100%);
            color: white;
            box-shadow: 0 4px 15px rgba(0, 59, 131, 0.3);
        }}
        .tab-btn .count {{
            background: rgba(255,255,255,0.2);
            padding: 2px 10px;
            border-radius: 12px;
            font-size: 13px;
        }}
        .tab-btn.active .count {{
            background: rgba(255,255,255,0.25);
        }}
        .tab-btn:not(.active) .count {{
            background: #e3f2fd;
            color: #003B83;
        }}
        
        .tab-content {{
            display: none;
        }}
        .tab-content.active {{
            display: block;
        }}
        
        .empty-state {{
            text-align: center;
            padding: 60px 20px;
            color: #546e7a;
            background: white;
            border-radius: 12px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.05);
        }}
        .empty-state .icon {{
            font-size: 48px;
            margin-bottom: 16px;
        }}
        
        .group-section {{ margin-bottom: 25px; }}
        .group-header {{ 
            background: linear-gradient(135deg, #002B61 0%, #003B83 100%);
            color: white; 
            padding: 16px 22px; 
            border-radius: 10px; 
            margin-bottom: 15px; 
            display: flex; 
            justify-content: space-between; 
            align-items: center;
            box-shadow: 0 4px 20px rgba(0, 43, 97, 0.3);
            border: 1px solid rgba(255,255,255,0.1);
        }}
        .group-header h2 {{ font-size: 19px; font-weight: 600; }}
        .group-header .count {{ 
            background: rgba(255,255,255,0.15); 
            padding: 6px 18px; 
            border-radius: 20px; 
            font-size: 14px;
            font-weight: 500;
        }}
        .entity-section {{ margin-left: 15px; margin-bottom: 20px; }}
        .sea-health-section {{ background: rgba(0, 59, 131, 0.03); border-radius: 8px; padding: 10px; margin-top: 10px; }}
        .sea-tag {{ background: linear-gradient(135deg, #10b981 0%, #059669 100%); }}
        .entity-header {{ 
            background: rgba(255,255,255,0.95); 
            padding: 14px 20px; 
            border-radius: 8px; 
            margin-bottom: 12px; 
            border-left: 5px solid #003B83;
            box-shadow: 0 2px 10px rgba(0,0,0,0.08);
        }}
        .entity-header h3 {{ color: #003B83; font-size: 16px; font-weight: 600; }}
        .news-item {{ 
            background: rgba(255,255,255,0.98); 
            padding: 18px 22px; 
            border-radius: 10px; 
            margin-bottom: 12px; 
            box-shadow: 0 3px 12px rgba(0,0,0,0.1);
            border: 1px solid rgba(0, 59, 131, 0.08);
            transition: all 0.2s ease;
        }}
        .news-item:hover {{ 
            transform: translateX(5px);
            box-shadow: 0 5px 20px rgba(0, 59, 131, 0.2);
            border-color: #0066E6;
        }}
        .news-meta {{
            display: flex;
            align-items: center;
            gap: 12px;
            margin-bottom: 10px;
        }}
        .entity-tag {{ 
            display: inline-block; 
            background: linear-gradient(135deg, #003B83 0%, #0052B8 100%);
            color: white; 
            padding: 4px 14px; 
            border-radius: 15px; 
            font-size: 12px; 
            font-weight: 500;
        }}
        .date-tag {{ color: #90a4ae; font-size: 12px; }}
        .news-title {{ 
            font-size: 16px; 
            line-height: 1.5;
            margin-bottom: 10px;
        }}
        .news-title a {{ 
            color: #003B83; 
            text-decoration: none; 
            font-weight: 600;
        }}
        .news-title a:hover {{ 
            color: #0052B8; 
            text-decoration: underline; 
        }}
        .news-summary {{ 
            color: #546e7a; 
            line-height: 1.7; 
            font-size: 14px; 
            background: #f8fafc; 
            padding: 12px 16px; 
            border-radius: 8px;
            border-left: 3px solid #003B83;
        }}
        
        /* 地图视图样式 */
        .view-toggle {{
            display: flex;
            gap: 0;
            margin-bottom: 20px;
            background: white;
            border-radius: 10px;
            overflow: hidden;
            box-shadow: 0 2px 10px rgba(0,0,0,0.1);
        }}
        .view-btn {{
            flex: 1;
            padding: 12px 20px;
            border: none;
            background: transparent;
            color: #546e7a;
            font-size: 14px;
            font-weight: 500;
            cursor: pointer;
            transition: all 0.2s ease;
        }}
        .view-btn:hover {{
            background: #e3f2fd;
            color: #003B83;
        }}
        .view-btn.active {{
            background: linear-gradient(135deg, #003B83 0%, #0052B8 100%);
            color: white;
        }}
        
        .map-container {{
            display: none;
            padding: 20px;
            background: white;
            border-radius: 12px;
            box-shadow: 0 4px 20px rgba(0,0,0,0.1);
            margin-bottom: 20px;
        }}
        .map-container.active {{
            display: block;
        }}
        
        .map-title {{
            text-align: center;
            color: #003B83;
            font-size: 18px;
            font-weight: 600;
            margin-bottom: 16px;
        }}
        
        .map-tabs {{
            display: flex;
            gap: 8px;
            margin-bottom: 20px;
            justify-content: center;
        }}
        .map-tab {{
            padding: 10px 20px;
            border: 2px solid #e3f2fd;
            background: white;
            color: #546e7a;
            font-size: 14px;
            font-weight: 500;
            cursor: pointer;
            border-radius: 25px;
            transition: all 0.2s ease;
            display: flex;
            align-items: center;
            gap: 6px;
        }}
        .map-tab:hover {{
            border-color: #003B83;
            color: #003B83;
            background: #f8fafc;
        }}
        .map-tab.active {{
            background: linear-gradient(135deg, #003B83 0%, #0052B8 100%);
            color: white;
            border-color: #003B83;
        }}
        .map-tab .count {{
            background: rgba(255,255,255,0.2);
            padding: 2px 8px;
            border-radius: 10px;
            font-size: 12px;
        }}
        .map-tab:not(.active) .count {{
            background: #e3f2fd;
            color: #003B83;
        }}
        
        .region-grid {{
            display: grid;
            grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
            gap: 16px;
        }}
        
        .region-card {{
            background: linear-gradient(135deg, #f8fafc 0%, #e3f2fd 100%);
            border: 2px solid #e3f2fd;
            border-radius: 12px;
            padding: 20px;
            text-align: center;
            cursor: pointer;
            transition: all 0.3s ease;
            position: relative;
            overflow: hidden;
        }}
        .region-card:hover {{
            transform: translateY(-5px);
            border-color: #003B83;
            box-shadow: 0 8px 25px rgba(0, 59, 131, 0.2);
        }}
        .region-card.has-news {{
            background: linear-gradient(135deg, #e3f2fd 0%, #bbdefb 100%);
        }}
        .region-card.no-news {{
            opacity: 0.6;
        }}
        .region-flag {{
            font-size: 36px;
            margin-bottom: 8px;
        }}
        .region-name {{
            color: #003B83;
            font-size: 16px;
            font-weight: 600;
            margin-bottom: 6px;
        }}
        .region-count {{
            color: #546e7a;
            font-size: 13px;
        }}
        .region-count span {{
            color: #003B83;
            font-weight: 700;
            font-size: 16px;
        }}
        
        .news-list-container {{
            display: block;
        }}
        .news-list-container.hidden {{
            display: none;
        }}
        
        .country-filter {{
            display: none;
            background: linear-gradient(135deg, #003B83 0%, #0052B8 100%);
            color: white;
            padding: 14px 20px;
            border-radius: 10px;
            margin-bottom: 15px;
            align-items: center;
            justify-content: space-between;
        }}
        .country-filter.active {{
            display: flex;
        }}
        .country-filter-name {{
            font-size: 16px;
            font-weight: 600;
        }}
        .country-filter-close {{
            background: rgba(255,255,255,0.2);
            border: none;
            color: white;
            padding: 6px 14px;
            border-radius: 20px;
            cursor: pointer;
            font-size: 13px;
        }}
        .country-filter-close:hover {{
            background: rgba(255,255,255,0.3);
        }}
        
        .footer {{
            text-align: center;
            padding: 25px;
            color: #546e7a;
            font-size: 14px;
            margin-top: 30px;
            background: rgba(255,255,255,0.8);
            border-radius: 10px;
            box-shadow: 0 2px 10px rgba(0,0,0,0.05);
        }}
    </style>
</head>
<body>
    <h1>🏥 海外医疗集团动态监测</h1>
    <div class="summary">
        <div class="summary-title">📊 数据概览</div>
        <div class="summary-stats">
            <div class="stat-item">
                <span class="stat-label">更新时间</span>
                <span class="stat-value">{datetime.now().strftime('%Y年%m月%d日 %H:%M')}</span>
            </div>
            <div class="stat-item">
                <span class="stat-label">监测范围</span>
                <span class="stat-value">{len(ENTITY_LOCATION)} 家机构</span>
            </div>
            <div class="stat-item" id="stat-active">
                <span class="stat-label" id="stat-label">今日动态</span>
                <span class="stat-value" id="stat-value">{today_active_entities} 家机构</span>
            </div>
        </div>
"""
    
    # 生成排行的辅助函数
    def render_ranking(ranking_data, title):
        if not ranking_data:
            return f"""
            <div class="ranking-section">
                <div class="ranking-title">{title}</div>
                <div class="ranking-empty">暂无动态</div>
            </div>
"""
        
        html_content = f"""
            <div class="ranking-section">
                <div class="ranking-title">{title}</div>
                <div class="ranking-list">
"""
        max_count = ranking_data[0][1]
        for i, (entity, count) in enumerate(ranking_data[:5], 1):
            bar_width = int(count / max_count * 100)
            html_content += f"""
                    <div class="ranking-item">
                        <span class="rank">{i}</span>
                        <span class="entity-name">{entity}</span>
                        <div class="bar-container">
                            <div class="bar" style="width: {bar_width}%"></div>
                        </div>
                        <span class="bar-count">{count} 条</span>
                    </div>
"""
        html_content += """
                </div>
            </div>
"""
        return html_content
    
    # 三个时间段的数据（供 JavaScript 使用）
    html += f"""
        <!-- 排行榜容器 -->
        <div id="ranking-container">
            {render_ranking(today_entity_ranking, "📈 今日机构动态排行")}
        </div>
        
        <!-- 隐藏的排行数据 -->
        <div id="ranking-today-data" style="display:none;">{render_ranking(today_entity_ranking, "📈 今日机构动态排行")}</div>
        <div id="ranking-last3days-data" style="display:none;">{render_ranking(last3days_entity_ranking, "📈 近3天机构动态排行")}</div>
        <div id="ranking-lastweek-data" style="display:none;">{render_ranking(lastweek_entity_ranking, "📈 近1周机构动态排行")}</div>
    </div>"""
    
    # 计算各国家/地区的新闻数量（三个时间段）
    location_counts_today = {}
    location_counts_3days = {}
    location_counts_week = {}
    
    for location in LOCATION_ORDER:
        location_counts_today[location] = sum(len(items) for items in grouped_today.get(location, {}).get("entities", {}).values()) if location in grouped_today else 0
        location_counts_3days[location] = sum(len(items) for items in grouped_3days.get(location, {}).get("entities", {}).values()) if location in grouped_3days else 0
        location_counts_week[location] = sum(len(items) for items in grouped_week.get(location, {}).get("entities", {}).values()) if location in grouped_week else 0
    
    # 国家旗帜映射
    location_flags = {
        "IHH集团": "🌐",
        "新加坡": "🇸🇬",
        "马来西亚": "🇲🇾",
        "泰国": "🇹🇭",
        "印度": "🇮🇳",
        "土耳其": "🇹🇷",
        "其他": "📍"
    }
    
    html += f"""
    <!-- 视图切换 -->
    <div class="view-toggle">
        <button class="view-btn active" onclick="switchView('list', this)">📋 列表视图</button>
        <button class="view-btn" onclick="switchView('map', this)">🗺️ 地图视图</button>
    </div>
    
    <!-- 地图视图 -->
    <div id="map-view" class="map-container">
        <div class="map-title">🌏 选择国家/地区查看动态</div>
        
        <!-- 地图内的时间选择 -->
        <div class="map-tabs">
            <button class="map-tab active" onclick="selectMapTime('today', this)">
                📅 今天 <span class="count">{len(today_news)}</span>
            </button>
            <button class="map-tab" onclick="selectMapTime('last3days', this)">
                📆 近3天 <span class="count">{len(last3days_news)}</span>
            </button>
            <button class="map-tab" onclick="selectMapTime('lastweek', this)">
                📋 近1周 <span class="count">{len(lastweek_news)}</span>
            </button>
        </div>
        
        <div class="region-grid" id="region-grid">
"""
    
    # 生成国家/地区卡片（默认显示今天的数据）
    for location in LOCATION_ORDER:
        count = location_counts_today.get(location, 0)
        flag = location_flags.get(location, "📍")
        card_class = "region-card has-news" if count > 0 else "region-card no-news"
        html += f"""
            <div class="{card_class}" data-location="{location}" onclick="filterByLocation('{location}')">
                <div class="region-flag">{flag}</div>
                <div class="region-name">{location}</div>
                <div class="region-count"><span class="count-num">{count}</span> 条动态</div>
            </div>
"""
    
    html += f"""
        </div>
    </div>
    
    <!-- 国家筛选提示 -->
    <div id="country-filter" class="country-filter">
        <span class="country-filter-name" id="filter-name">全部地区</span>
        <button class="country-filter-close" onclick="clearFilter()">✕ 清除筛选</button>
    </div>
    
    <div class="tabs">
        <button class="tab-btn active" onclick="showTab('today', this)">
            📅 今天 <span class="count">{len(today_news)}</span>
        </button>
        <button class="tab-btn" onclick="showTab('last3days', this)">
            📆 近3天 <span class="count">{len(last3days_news)}</span>
        </button>
        <button class="tab-btn" onclick="showTab('lastweek', this)">
            📋 近1周 <span class="count">{len(lastweek_news)}</span>
        </button>
    </div>
"""
    
    # 生成新闻列表的辅助函数
    def render_news_list(grouped_data, sea_grouped=None):
        """渲染新闻列表 HTML"""
        if not grouped_data:
            return """
        <div class="empty-state">
            <div class="icon">📭</div>
            <div>暂无新闻动态</div>
        </div>
"""
        
        # 国家旗帜映射
        location_flags = {
            "IHH集团": "🌐",
            "新加坡": "🇸🇬",
            "马来西亚": "🇲🇾",
            "泰国": "🇹🇭",
            "印度": "🇮🇳",
            "土耳其": "🇹🇷",
            "其他": "📍"
        }
        
        html_content = ""
        for location in LOCATION_ORDER:
            if location not in grouped_data:
                continue
                
            location_data = grouped_data[location]
            total_items = sum(len(items) for items in location_data["entities"].values())
            flag = location_flags.get(location, "📍")
            
            # 计算该国家的东南亚动态数量
            sea_items = sea_grouped.get(location, []) if sea_grouped else []
            total_with_sea = total_items + len(sea_items)
            
            html_content += f"""
    <div class="group-section">
        <div class="group-header">
            <h2>{flag} {location}</h2>
            <span class="count">{total_with_sea} 条动态</span>
        </div>
"""
            
            # 渲染机构新闻
            for entity, items in sorted(location_data["entities"].items(), key=lambda x: -len(x[1])):
                html_content += f"""
        <div class="entity-section">
            <div class="entity-header">
                <h3>📍 {entity} ({len(items)} 条)</h3>
            </div>
"""
                for item in items:
                    title = item.get("title", "无标题")
                    snippet = item.get("snippet", item.get("description", ""))
                    # 使用 AI 生成中文摘要
                    summary = summarize_text(snippet, 80, title)
                    
                    html_content += f"""
            <div class="news-item">
                <div class="news-meta">
                    <span class="entity-tag">{item.get('entity_name', '')}</span>
                    <span class="date-tag">{item.get('date', '')}</span>
                </div>
                <h4 class="news-title"><a href="{item.get('url', '#')}" target="_blank">{title}</a></h4>
                <div class="news-summary">{summary}</div>
            </div>
"""
                html_content += "        </div>\n"
            
            # 渲染该国家的东南亚卫生动态
            if sea_items:
                html_content += f"""
        <div class="entity-section sea-health-section">
            <div class="entity-header">
                <h3>🌏 卫生动态 ({len(sea_items)} 条)</h3>
            </div>
"""
                for item in sea_items:
                    title = item.get("title", "无标题")
                    snippet = item.get("snippet", item.get("description", ""))
                    summary = summarize_text(snippet, 80, title)
                    
                    html_content += f"""
            <div class="news-item">
                <div class="news-meta">
                    <span class="entity-tag sea-tag">政策动态</span>
                    <span class="date-tag">{item.get('date', '')}</span>
                </div>
                <h4 class="news-title"><a href="{item.get('url', '#')}" target="_blank">{title}</a></h4>
                <div class="news-summary">{summary}</div>
            </div>
"""
                html_content += "        </div>\n"
            
            html_content += "    </div>\n"
        
        return html_content
    
    # 生成三个标签页的内容
    html += f"""
    <!-- 今天 -->
    <div id="tab-today" class="tab-content active">
        {render_news_list(grouped_today, sea_grouped_today)}
    </div>
    
    <!-- 过去3天 -->
    <div id="tab-last3days" class="tab-content">
        {render_news_list(grouped_3days, sea_grouped_3days)}
    </div>
    
    <!-- 过去1周 -->
    <div id="tab-lastweek" class="tab-content">
        {render_news_list(grouped_week, sea_grouped_week)}
    </div>
    
    <script>
        // 时间段统计数据
        const statsData = {{
            today: {{ label: '今日动态', value: '{today_active_entities} 家机构' }},
            last3days: {{ label: '近3天动态', value: '{last3days_active_entities} 家机构' }},
            lastweek: {{ label: '近1周动态', value: '{lastweek_active_entities} 家机构' }}
        }};
        
        // 各时间段的国家新闻数量
        const locationCounts = {{
            today: {json.dumps(location_counts_today)},
            last3days: {json.dumps(location_counts_3days)},
            lastweek: {json.dumps(location_counts_week)}
        }};
        
        let currentView = 'list';
        let currentFilter = null;
        let currentTab = 'today';
        
        // 切换视图
        function switchView(view, btn) {{
            currentView = view;
            document.querySelectorAll('.view-btn').forEach(el => el.classList.remove('active'));
            btn.classList.add('active');
            
            if (view === 'map') {{
                document.getElementById('map-view').classList.add('active');
                document.querySelectorAll('.tab-content').forEach(el => el.style.display = 'none');
                document.querySelector('.tabs').style.display = 'none';
                // 同步地图内的时间选择
                document.querySelectorAll('.map-tab').forEach(el => el.classList.remove('active'));
                document.querySelector('.map-tab[onclick*="' + currentTab + '"]').classList.add('active');
                updateMapData(currentTab);
            }} else {{
                document.getElementById('map-view').classList.remove('active');
                document.querySelectorAll('.tab-content').forEach(el => {{
                    el.style.display = el.classList.contains('active') ? 'block' : 'none';
                }});
                document.querySelector('.tabs').style.display = 'flex';
            }}
        }}
        
        // 更新地图数据
        function updateMapData(tabName) {{
            const counts = locationCounts[tabName];
            document.querySelectorAll('.region-card').forEach(card => {{
                const location = card.getAttribute('data-location');
                const count = counts[location] || 0;
                card.querySelector('.count-num').textContent = count;
                card.classList.remove('has-news', 'no-news');
                card.classList.add(count > 0 ? 'has-news' : 'no-news');
            }});
        }}
        
        // 地图内时间选择
        function selectMapTime(tabName, btn) {{
            currentTab = tabName;
            document.querySelectorAll('.map-tab').forEach(el => el.classList.remove('active'));
            btn.classList.add('active');
            updateMapData(tabName);
        }}
        
        // 按国家筛选
        function filterByLocation(location) {{
            currentFilter = location;
            
            // 切换到列表视图
            document.querySelectorAll('.view-btn').forEach(el => el.classList.remove('active'));
            document.querySelector('.view-btn').classList.add('active');
            document.getElementById('map-view').classList.remove('active');
            document.querySelector('.tabs').style.display = 'flex';
            
            // 同步时间选择到列表视图
            document.querySelectorAll('.tab-content').forEach(el => {{
                el.classList.remove('active');
                el.style.display = 'none';
            }});
            document.querySelectorAll('.tab-btn').forEach(el => el.classList.remove('active'));
            
            // 激活当前时间对应的标签页
            const activeTab = document.getElementById('tab-' + currentTab);
            activeTab.classList.add('active');
            activeTab.style.display = 'block';
            document.querySelector('.tab-btn[onclick*="' + currentTab + '"]').classList.add('active');
            
            // 更新统计和排行榜
            document.getElementById('stat-label').textContent = statsData[currentTab].label;
            document.getElementById('stat-value').textContent = statsData[currentTab].value;
            const rankingHtml = document.getElementById('ranking-' + currentTab + '-data').innerHTML;
            document.getElementById('ranking-container').innerHTML = rankingHtml;
            
            // 显示国家筛选提示
            document.getElementById('country-filter').classList.add('active');
            document.getElementById('filter-name').textContent = location + ' 动态';
            
            // 筛选对应国家的新闻
            document.querySelectorAll('.group-section').forEach(el => {{
                const headerText = el.querySelector('.group-header h2').textContent;
                if (headerText.includes(location)) {{
                    el.style.display = 'block';
                }} else {{
                    el.style.display = 'none';
                }}
            }});
        }}
        
        // 清除筛选
        function clearFilter() {{
            currentFilter = null;
            document.getElementById('country-filter').classList.remove('active');
            document.querySelectorAll('.group-section').forEach(el => {{
                el.style.display = 'block';
            }});
        }}
        
        function showTab(tabName, btn) {{
            currentTab = tabName;
            document.querySelectorAll('.tab-content').forEach(el => {{
                el.classList.remove('active');
                el.style.display = 'none';
            }});
            document.querySelectorAll('.tab-btn').forEach(el => {{
                el.classList.remove('active');
            }});
            const activeContent = document.getElementById('tab-' + tabName);
            activeContent.classList.add('active');
            activeContent.style.display = 'block';
            btn.classList.add('active');
            
            document.getElementById('stat-label').textContent = statsData[tabName].label;
            document.getElementById('stat-value').textContent = statsData[tabName].value;
            
            const rankingHtml = document.getElementById('ranking-' + tabName + '-data').innerHTML;
            document.getElementById('ranking-container').innerHTML = rankingHtml;
            
            if (currentFilter) clearFilter();
        }}
    </script>
    
    <div class="footer">
        📌 数据来源：Firecrawl 搜索引擎 | 自动采集，每日更新
    </div>
</body>
</html>"""
    
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(html)
    
    print(f"   ✅ HTML: {output_path}")
    return output_path


def main():
    parser = argparse.ArgumentParser(description="海外医疗集团动态监测")
    parser.add_argument("--dry-run", action="store_true", help="测试模式")
    parser.add_argument("--output", choices=["json", "html", "both"], default="json")
    parser.add_argument("--incremental", action="store_true", help="增量更新模式：只搜索新新闻，合并历史数据")
    args = parser.parse_args()
    
    print(f"{'='*60}")
    print(f"海外医疗集团动态监测 - {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    if args.incremental:
        print(f"模式: 增量更新（保留7天数据）")
    print(f"{'='*60}")
    
    # 加载配置
    targets = json.load(open(CONFIG_DIR / "targets.json"))
    search_config = targets.get("search_config", {})
    
    # 增量模式：加载历史数据
    existing_institutions = []
    existing_sea = []
    if args.incremental:
        print("\n📂 加载历史数据...")
        existing_institutions, existing_sea = load_existing_news()
        # 增量模式只搜索最近的新闻
        search_config = {**search_config, "default_time_range": "1d"}
    
    all_news = []
    
    # 搜索各机构
    print("\n📡 搜索目标机构动态...")
    for group in targets.get("groups", []):
        print(f"\n  ▶ {group['name']}")
        
        # 处理带 markets 的组（如 IHH）
        if "markets" in group:
            for market in group["markets"]:
                print(f"    [{market['region']}]")
                for entity in market.get("entities", []):
                    news = search_entity_news(entity, search_config)
                    all_news.extend(news)
        # 处理直接 entities 的组
        elif "entities" in group:
            for entity in group["entities"]:
                news = search_entity_news(entity, search_config)
                all_news.extend(news)
    
    # 搜索行业新闻源
    print("\n📡 搜索行业新闻源...")
    for source in targets.get("news_sources", []):
        news = search_news_sources(source, search_config)
        all_news.extend(news)
    
    # 搜索东南亚卫生健康动态
    print("\n📡 搜索东南亚卫生健康动态...")
    sea_news = search_sea_health_news(targets)
    print(f"   东南亚动态: {len(sea_news)} 条")
    
    # 去重（验证链接有效性）
    print(f"\n📊 采集结果: {len(all_news)} 条")
    unique_news = deduplicate_news(all_news, validate_links=True)
    print(f"   去重后: {len(unique_news)} 条")
    
    # 东南亚新闻去重
    if sea_news:
        unique_sea = deduplicate_news(sea_news, validate_links=False)
        print(f"   东南亚去重后: {len(unique_sea)} 条")
    else:
        unique_sea = []
    
    # 增量模式：合并历史数据并清理过期数据
    if args.incremental:
        print(f"\n📋 合并历史数据...")
        print(f"   新采集: {len(unique_news)} 条 | 历史: {len(existing_institutions)} 条")
        unique_news = merge_and_cleanup_news(existing_institutions, unique_news, max_days=7)
        unique_sea = merge_and_cleanup_news(existing_sea, unique_sea, max_days=7)
        print(f"   合并后: {len(unique_news)} 条机构新闻, {len(unique_sea)} 条东南亚动态")
    
    # 保存数据
    today = datetime.now().strftime("%Y-%m-%d")
    (DATA_DIR / "parsed" / today).mkdir(parents=True, exist_ok=True)
    
    # JSON 输出
    if args.output in ["json", "both"]:
        json_file = DATA_DIR / "parsed" / today / "news.json"
        with open(json_file, "w", encoding="utf-8") as f:
            json.dump({"institutions": unique_news, "sea_health": unique_sea}, f, ensure_ascii=False, indent=2)
        print(f"   ✅ JSON: {json_file}")
    
    # HTML 输出
    if args.output in ["html", "both"]:
        html_file = DATA_DIR / "parsed" / today / "report.html"
        generate_html(unique_news, html_file, sea_news=unique_sea)
        print(f"   ✅ HTML: {html_file}")
    
    # 写入飞书
    if not args.dry_run and unique_news:
        print("\n📤 写入飞书表格...")
        if save_to_feishu(unique_news, FEISHU_CONFIG):
            print("   ✅ 写入成功")
        else:
            print("   ⚠️ 写入失败")
    
    # 自动部署到 GitHub Pages
    if not args.dry_run and args.output in ["html", "both"]:
        print("\n🚀 部署到 GitHub Pages...")
        try:
            import sys
            sys.path.insert(0, str(SKILL_DIR / "deploy"))
            from github_pages import deploy_html
            
            html_file = DATA_DIR / "parsed" / today / "report.html"
            url = deploy_html(str(html_file), "index.html")
            if url:
                print(f"   ✅ 部署成功: {url}")
        except Exception as e:
            print(f"   ⚠️ 部署失败: {e}")
    
    print(f"\n{'='*60}")
    print(f"完成 - 采集 {len(unique_news)} 条新闻")
    
    return {"total": len(unique_news)}


if __name__ == "__main__":
    main()
