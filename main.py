import os
import sys
import datetime
import requests
import json
import chinese_calendar as calendar
from openai import OpenAI
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.header import Header
import markdown # 用于将 Markdown 转为 HTML 邮件

# 1. 加载环境变量
TARGET_COMPANIES = os.getenv("TARGET_COMPANIES", "威海光威复合材料 威海广泰 迪尚集团")
SEARCH_API_KEY = os.getenv("SEARCH_API_KEY")

LLM_API_KEY = os.getenv("LLM_API_KEY")
LLM_BASE_URL = os.getenv("LLM_BASE_URL", "https://api.openai.com/v1") 
LLM_MODEL = os.getenv("LLM_MODEL", "gpt-4o") 

# 邮件相关变量
EMAIL_SENDER = os.getenv("EMAIL_SENDER")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")
EMAIL_RECEIVERS = os.getenv("EMAIL_RECEIVERS")
SMTP_SERVER = "smtp.qq.com" # 默认使用 QQ 邮箱服务器，若用网易请改为 smtp.163.com
SMTP_PORT = 465             # SSL 默认端口

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
    client = OpenAI(api_key=LLM_API_KEY, base_url=LLM_BASE_URL) 
    
    prompt = f"""
    【你的角色与受众】
    你是一名客观、严谨、务实的商业情报分析师。
    你的报告阅读对象是：中国大陆山东省威海市的常驻居民及一线业务人员。

    【核心工作纪律 - 防幻觉机制（最高优先级）】
    1. 忠于事实：所有的总结、数据、政策名称必须 100% 来源于我下方提供的搜索原文。
    2. 严禁脑补：如果提供的原文中没有相关信息或动态，请直接写“本周暂无相关关键动态”，绝对禁止调用你的内部知识库去编造。
    3. 语言规范：必须使用极其客观、平实、直白的新闻报道体。严禁使用任何比喻、拟人、夸张等修辞手法。不讲废话，直击核心数据与事件。

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
        temperature=0.1 
    )
    return response.choices[0].message.content

# 5. 发送邮件功能
def send_email(subject, markdown_content):
    if not EMAIL_SENDER or not EMAIL_PASSWORD:
        print("未配置发件人邮箱或密码，跳过邮件发送。")
        return

    # 逻辑：如果收件人留空，则发给自己；否则按逗号分隔多个收件人
    if not EMAIL_RECEIVERS or EMAIL_RECEIVERS.strip() == "":
        receivers_list = [EMAIL_SENDER]
    else:
        # 支持中英文逗号分割
        clean_receivers = EMAIL_RECEIVERS.replace('，', ',')
        receivers_list = [r.strip() for r in clean_receivers.split(',') if r.strip()]

    # 将 Markdown 转为 HTML，方便在邮件客户端中优雅地阅读
    html_content = markdown.markdown(markdown_content)
    # 添加简单的 CSS 样式让邮件更美观
    full_html = f"""
    <html>
    <head><style>body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }} h2 {{ color: #2c3e50; border-bottom: 1px solid #eee; padding-bottom: 5px; }}</style></head>
    <body>{html_content}</body>
    </html>
    """

    msg = MIMEMultipart()
    msg['From'] = Header(f"威海商业情报助手 <{EMAIL_SENDER}>")
    msg['To'] = Header(", ".join(receivers_list))
    msg['Subject'] = Header(subject, 'utf-8')
    msg.attach(MIMEText(full_html, 'html', 'utf-8'))

    try:
        server = smtplib.SMTP_SSL(SMTP_SERVER, SMTP_PORT)
        server.login(EMAIL_SENDER, EMAIL_PASSWORD)
        server.sendmail(EMAIL_SENDER, receivers_list, msg.as_string())
        server.quit()
        print(f"✅ 邮件已成功发送至: {', '.join(receivers_list)}")
    except Exception as e:
        print(f"❌ 邮件发送失败: {e}")

# --- 主程序入口 ---
if __name__ == "__main__":
    if TRIGGER_EVENT == "schedule":
        if not is_first_workday_of_week():
            print("今天不是本周首个工作日，任务跳过。")
            sys.exit(0)
            
    print("开始执行情报收集...")
    
    comp_raw = search_info(f"{TARGET_COMPANIES} 最新公司动态 商业新闻")
    weihai_raw = search_info("威海市 重点舆情 新闻 政策颁布 行业扶持 经济指标 外经外贸 招商引资 最新动态")
    macro_raw = search_info("中国宏观经济变化 重点政策 十五五规划 两会 中央经济工作会议 重点指标 LPR 关税 最新新闻")
    global_raw = search_info("Global economic trade financial news international situation latest trends")
    
    print("信息收集完毕，正在呼叫大模型进行严谨提炼...")
    briefing = generate_briefing(comp_raw, weihai_raw, macro_raw, global_raw)
    
    print("简报生成完毕，准备发送邮件...")
    # 动态生成邮件标题，带上今天的日期
    today_str = datetime.date.today().strftime("%Y-%m-%d")
    email_subject = f"【威海业务情报周报】{today_str}"
    
    send_email(email_subject, briefing)
    print("流程全部执行成功！")
