import os
import sys
import datetime
import requests
import json
import chinese_calendar as calendar
from openai import OpenAI

# 1. 加载环境变量 (支持动态切换模型和关注企业)
TARGET_COMPANIES = os.getenv("TARGET_COMPANIES", "这里可以填入你关注的具体公司名称，用空格隔开")
SEARCH_API_KEY = os.getenv("SEARCH_API_KEY")

# LLM 动态配置 (默认兼容 OpenAI 格式的调用)
LLM_API_KEY = os.getenv("LLM_API_KEY")
# 如果使用国内模型，只需在 GitHub Variables 配置对应的 BASE_URL (例如 DeepSeek: https://api.deepseek.com/v1)
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://api.openai.com/v1") 
LLM_MODEL = os.getenv("LLM_MODEL", "gpt-4o") 

WEBHOOK_URL = os.getenv("WEBHOOK_URL")
TRIGGER_EVENT = os.getenv("TRIGGER_EVENT", "schedule")

# 2. 节假日检测逻辑
def is_first_workday_of_week():
    today = datetime.date.today()
    if not calendar.is_workday(today):
        return False
    weekday = today.weekday()
    for i in range(weekday):
        prev_day = today - datetime.timedelta(days=weekday - i)
        if calendar.is_workday(prev_day):
            return False
    return True

# 3. 定向搜索函数
def search_info(query, days=7):
    url = "https://api.tavily.com/search"
    payload = {
        "api_key": SEARCH_API_KEY,
        "query": query,
        "search_depth": "advanced",
        "include_answer": True,
        "days": days
    }
    try:
        response = requests.post(url, json=payload).json()
        return "\n".join([result.get('content', '') for result in response.get('results', [])])
    except Exception as e:
        print(f"搜索出错 [{query}]: {e}")
        return "暂无相关搜索结果"

# 4. LLM 整理与防幻觉生成
def generate_briefing(companies_info, weihai_info, macro_info, global_info):
    # 动态初始化 LLM 客户端
    client = OpenAI(
        api_key=LLM_API_KEY,
        base_url=LLM_BASE_URL
    ) 
    
    prompt = f"""
    【你的角色与受众】
    你是一名客观、严谨、务实的商业情报分析师。
    你的报告阅读对象是：中国大陆山东省威海市的常驻居民及一线业务人员。

    【核心工作纪律 - 防幻觉机制（最高优先级）】
    1. 忠于事实：所有的总结、数据、政策名称（如十五五、LPR、关税等）必须 **100% 来源于我下方提供的搜索原文**。
    2. 严禁脑补：如果提供的原文中没有相关信息或动态，请直接写“本周暂无相关关键动态”，**绝对禁止**调用你的内部知识库去编造、猜测或补充任何内容。
    3. 语言规范：必须使用极其客观、平实、直白的新闻报道体。**严禁**使用任何比喻、拟人、夸张等修辞手法（禁止出现诸如“春风化雨”、“重磅炸弹”、“扬帆起航”、“迎来春天”等浮夸词汇）。不讲废话，直击核心数据与事件。

    【请基于以下四块原始素材，生成本周商业情报参考】

    素材A（关注企业动态）：{companies_info}
    素材B（威海本地政经与外贸）：{weihai_info}
    素材C（中国宏观政策与经济指标）：{macro_info}
    素材D（全球经贸与国际局势）：{global_info}

    【输出格式要求】
    请使用清晰的 Markdown 排版，分四个独立模块（关注企业、威海本地、全国宏观、全球局势）输出。
    每一条简报后，用一句话客观说明该事件对威海本地业务人员在客户沟通或业务开拓上的“参考方向”。
    """
    
    response = client.chat.completions.create(
        model=LLM_MODEL,
        messages=[{"role": "user", "content": prompt}],
        temperature=0.1 # 极低的温度，大幅度减少发散和幻觉
    )
    return response.choices[0].message.content

# 5. 推送 Webhook
def push_to_webhook(content):
    headers = {"Content-Type": "application/json"}
    payload = {"msgtype": "markdown", "markdown": {"content": content}}
    requests.post(WEBHOOK_URL, headers=headers, data=json.dumps(payload))

# --- 主程序入口 ---
if __name__ == "__main__":
    if TRIGGER_EVENT == "schedule":
        if not is_first_workday_of_week():
            print("今天不是本周首个工作日，任务跳过。")
            sys.exit(0)
            
    print("开始执行情报收集...")
    
    # a. 特定企业搜索
    comp_query = f"{TARGET_COMPANIES} 最新公司动态 商业新闻 业务进展"
    comp_raw = search_info(comp_query)
    
    # b. 威海重点政经搜索
    weihai_query = "威海市 重点舆情 新闻 政策颁布 行业扶持 经济指标 外经外贸 招商引资 最新动态"
    weihai_raw = search_info(weihai_query)
    
    # c. 中国宏观与政策搜索
    macro_query = "中国宏观经济变化 重点政策 十五五规划 两会 中央经济工作会议 重点指标 LPR 关税 最新新闻"
    macro_raw = search_info(macro_query)
    
    # d. 世界局势与宏观搜索
    global_query = "Global economic trade financial news international situation latest trends"
    global_raw = search_info(global_query)
    
    print("信息收集完毕，正在呼叫大模型进行严谨提炼...")
    briefing = generate_briefing(comp_raw, weihai_raw, macro_raw, global_raw)
    
    print("简报生成完毕，准备推送到群聊...")
    push_to_webhook(briefing)
    print("执行成功！")
