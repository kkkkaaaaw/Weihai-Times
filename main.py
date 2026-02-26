import os
import sys
import datetime
import time
import requests
import json
import chinese_calendar as calendar
from openai import OpenAI
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.header import Header
from email.utils import formataddr
import markdown

# ==========================================
# 1. 读取环境变量
# ==========================================
# 业务变量 (如果在 GitHub 没配，就用这里的默认值)
TARGET_COMPANIES = os.getenv("TARGET_COMPANIES") or "威海光威复合材料 威海广泰 迪尚集团 威高集团"
TARGET_INDUSTRY = os.getenv("TARGET_INDUSTRY") or "低空经济与跨境电商"

SEARCH_API_KEY = os.getenv("SEARCH_API_KEY")

# 模型配置
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3-flash-preview")
GEMINI_MODEL_FALLBACK = os.getenv("GEMINI_MODEL_FALLBACK", "gemini-2.5-flash")
GEMINI_REQUEST_DELAY = float(os.getenv("GEMINI_REQUEST_DELAY", "3.0"))

# 备用/国产模型配置
CUSTOM_API_KEY = os.getenv("CUSTOM_API_KEY")
CUSTOM_BASE_URL = os.getenv("CUSTOM_BASE_URL")
CUSTOM_MODEL = os.getenv("CUSTOM_MODEL")

EMAIL_SENDER = os.getenv("EMAIL_SENDER")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")
EMAIL_RECEIVERS = os.getenv("EMAIL_RECEIVERS")
SMTP_SERVER = "smtp.qq.com" 

TRIGGER_EVENT = os.getenv("TRIGGER_EVENT", "schedule")
# 获取今日标准时间字符串
TODAY_STR = datetime.date.today().strftime("%Y年%m月%d日")

# ==========================================
# 2. 核心业务逻辑
# ==========================================
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

# 升级后的搜索函数：同时抓取内容和来源 URL
def search_info(query, days=7):
    url = "https://api.tavily.com/search"
    payload = {
        "api_key": SEARCH_API_KEY,
        "query": query,
        "search_depth": "advanced",
        "include_answer": False, # 关闭总结，只要原始网址和摘要
        "days": days
    }
    try:
        response = requests.post(url, json=payload).json()
        results_str = []
        for result in response.get('results', []):
            content = result.get('content', '').replace('\n', ' ')
            source_url = result.get('url', '无来源链接')
            results_str.append(f"【内容】: {content} \n【来源】: {source_url}\n")
        return "\n".join(results_str) if results_str else "暂无相关搜索结果"
    except Exception as e:
        print(f"搜索出错 [{query}]: {e}")
        return "暂无相关搜索结果"

def get_llm_client():
    """根据是否配置了自定义大模型，智能选择客户端"""
    if CUSTOM_API_KEY:
        print("检测到备用模型 (CUSTOM_API_KEY)，将使用备用通道...")
        base_url = CUSTOM_BASE_URL or "https://api.deepseek.com"
        model = CUSTOM_MODEL or "deepseek-chat"
        return OpenAI(api_key=CUSTOM_API_KEY, base_url=base_url), model, False
    else:
        print("使用默认 Gemini 通道...")
        client = OpenAI(
            api_key=GEMINI_API_KEY, 
            base_url="https://generativelanguage.googleapis.com/v1beta/openai/"
        )
        return client, GEMINI_MODEL, True

def generate_briefing(client, model_name, is_gemini, companies_info, weihai_info, ind_info, macro_global_info, tech_info):
    prompt = f"""
    【角色与纪律要求】
    你是“一名专业的顶尖投行研究所首席专家”，负责为业务团队提供高度聚焦、客观、真实的商业简报。
    系统当前时间为：{TODAY_STR}。你必须严格基于此时间点，只总结最近一周的最新动态。

    【防幻觉与强硬规则】
    1. 真实溯源：你在报告中写的**每一条**新闻，必须在结尾附上我提供的对应【来源】URL链接。绝不可自己编造链接！
    2. 拒绝宏大叙事：在宏观和全球局势板块，严禁写诸如“全球经济放缓”等废话，必须写出具体的“近期重点事件”（如某项关税政策落地、某个具体国家的大选结果、某机构的最新具体数据等）。
    3. 客观直白：禁止使用比喻、拟人等修辞手法。
    4. 附上新闻的2-3个关键词。

    【信息素材池】
    素材A（关注企业）：{companies_info}
    素材B（威海政经）：{weihai_info}
    素材C（关注行业 - {TARGET_INDUSTRY}）：{ind_info}
    素材D（宏观与全球重点事件）：{macro_global_info}
    素材E（前沿科技杂谈）：{tech_info}

    【强制输出格式模板】（请直接复制以下Markdown结构并填入内容，不要输出任何额外的开头或结尾寒暄语）：

    # 商业情报周报

    **报告日期：** {TODAY_STR} | **发件人：** 威海营业部首席新闻官
    ---

    ## 一、 重点企业动态
    （提取1-3条最有商业价值的动态。格式要求：一句话事件核心概述 + 业务参考方向 + [来源地址]）

    ## 二、 威海本地政经
    （提取1-3条本地政策或大事件。格式要求：一句话事件核心概述 + 业务参考方向 + [来源地址]）

    ## 三、 【{TARGET_INDUSTRY}】行业风向
    （提取1-3条该行业的近期重大新闻。格式要求：一句话事件核心概述 + 业务参考方向 + [来源地址]）

    ## 四、 宏观与全球重点局势
    （提取1-3个具体的、近期发生的全球/全国大事件。格式要求：一句话事件核心概述 + 业务参考方向 + [来源地址]）

    ## 五、 科技前沿杂谈（AI/机器人/新能源）
    （寻找最近一周内，这三个领域最前沿的技术突破或巨头动向，作为客户经理拓展视野的谈资。格式要求：一句话事件核心概述 + 业务参考方向 + [来源地址]）
    """
    
    if is_gemini:
        time.sleep(GEMINI_REQUEST_DELAY)

    try:
        response = client.chat.completions.create(
            model=model_name,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1 
        )
        return response.choices[0].message.content
    except Exception as e:
        print(f"⚠️ 主模型 {model_name} 请求失败: {e}")
        if is_gemini:
            print(f"🔄 尝试使用备用模型 {GEMINI_MODEL_FALLBACK}...")
            try:
                time.sleep(GEMINI_REQUEST_DELAY)
                fallback_response = client.chat.completions.create(
                    model=GEMINI_MODEL_FALLBACK,
                    messages=[{"role": "user", "content": prompt}],
                    temperature=0.1 
                )
                return fallback_response.choices[0].message.content
            except Exception as fallback_e:
                print(f"❌ 备用模型也失败: {fallback_e}")
        return "生成简报失败，请检查 API Key 或网络状态。"

def send_email(subject, markdown_content):
    if not EMAIL_SENDER or not EMAIL_PASSWORD:
        print("未配置邮箱参数，跳过发送。")
        return

    receivers_list = [EMAIL_SENDER] if not EMAIL_RECEIVERS else [r.strip() for r in EMAIL_RECEIVERS.replace('，', ',').split(',') if r.strip()]

    html_content = markdown.markdown(markdown_content)
    # 增加了一些简单的 CSS 样式，让主标题更大更清晰
    full_html = f"""
    <html>
    <head><style>
        body {{ font-family: 'Microsoft YaHei', sans-serif; line-height: 1.6; color: #333; }} 
        h1 {{ color: #1a365d; font-size: 24px; border-bottom: 2px solid #1a365d; padding-bottom: 10px; }}
        h2 {{ color: #2c3e50; font-size: 18px; border-bottom: 1px dashed #ccc; padding-bottom: 5px; margin-top: 25px; }}
        a {{ color: #3498db; text-decoration: none; word-break: break-all; }}
    </style></head>
    <body>{html_content}</body>
    </html>
    """

    msg = MIMEMultipart()
    msg['From'] = formataddr(("威海营业部首席新闻官", EMAIL_SENDER))
    msg['To'] = ", ".join(receivers_list)
    msg['Subject'] = Header(subject, 'utf-8')
    msg.attach(MIMEText(full_html, 'html', 'utf-8'))

    try:
        server = smtplib.SMTP_SSL(SMTP_SERVER, 465, timeout=15)
        server.login(EMAIL_SENDER, EMAIL_PASSWORD)
        server.sendmail(EMAIL_SENDER, receivers_list, msg.as_string())
        server.quit()
        print(f"✅ 邮件已通过 465 端口成功发送")
    except Exception as e1:
        print(f"⚠️ 465 端口失败 ({e1})，尝试 587 端口...")
        try:
            time.sleep(3) 
            server = smtplib.SMTP(SMTP_SERVER, 587, timeout=15)
            server.starttls() 
            server.login(EMAIL_SENDER, EMAIL_PASSWORD)
            server.sendmail(EMAIL_SENDER, receivers_list, msg.as_string())
            server.quit()
            print(f"✅ 邮件已通过备用端口 587 成功发送")
        except Exception as e2:
            print(f"❌ 邮件发送最终失败: {e2}")

# --- 主程序 ---
if __name__ == "__main__":
    if TRIGGER_EVENT == "schedule" and not is_first_workday_of_week():
        print("今日非首个工作日，跳过。")
        sys.exit(0)
            
    llm_client, model_name, is_gemini = get_llm_client()
    
    print("-> 搜集企业动态...")
    comp_raw = search_info(f"{TARGET_COMPANIES} 最新 突发 重大商业新闻")
    print("-> 搜集威海政经...")
    weihai_raw = search_info("威海市 最新 突发 重点舆情 招商引资 政策落地 新闻")
    print(f"-> 搜集行业风向 ({TARGET_INDUSTRY})...")
    ind_raw = search_info(f"{TARGET_INDUSTRY} 行业最新 突发 重大变革 新闻")
    print("-> 搜集宏观与全球局势...")
    macro_global_raw = search_info("中国宏观经济 重点政策落地 OR Global international major events breaking news")
    print("-> 搜集科技杂谈...")
    tech_raw = search_info("前沿科技 人工智能 AI 机器人 新能源 最新技术突破 巨头动向")
    
    print("信息收集完毕，正在呼叫大模型...")
    briefing = generate_briefing(llm_client, model_name, is_gemini, comp_raw, weihai_raw, ind_raw, macro_global_raw, tech_raw)
    
    email_subject = f"【威海商业情报】{TODAY_STR}"
    send_email(email_subject, briefing)
    print("流程全部执行成功！")
