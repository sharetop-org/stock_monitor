import requests
import json
import re
import random

def get_industry_compare(stock_code, market="1"):
    """
    获取指定股票的行业对比数据（包含行业平均、排名、四分位）
    :param stock_code: 股票代码，如 '300059'
    :param market: 市场代码，'1' 上海，'0' 深圳
    :return: dict 包含股票数据和行业平均数据
    """
    # 构造 SECUCODE
    secucode = f"{market}.{stock_code}"

    # 推测的报表名称（可能需要根据实际抓包修改）
    report_name = "RPT_FINANCE_COMPARE"  # 尝试此名称，若不对可替换为 "RPT_STOCK_INDUSTRY_COMPARE"

    # 需要获取的字段（英文，需要根据实际接口调整）
    # 以下字段名是常见财务指标英文，但实际可能不同，请以抓包结果为准
    columns = [
        "SECUCODE",
        "TOTAL_MARKET_CAP",         # 总市值
        "NET_ASSETS",               # 净资产
        "NET_PROFIT",               # 净利润
        "PE_DYNAMIC",               # 市盈率(动)
        "PB_RATIO",                 # 市净率
        "GROSS_MARGIN",             # 毛利率
        "NET_MARGIN",               # 净利率
        "ROE",                      # ROE
        "TOTAL_MARKET_CAP_RANK",    # 总市值行业排名
        "TOTAL_MARKET_CAP_QUARTILE",# 总市值四分位
        "NET_ASSETS_RANK",
        "NET_ASSETS_QUARTILE",
        "NET_PROFIT_RANK",
        "NET_PROFIT_QUARTILE",
        "PE_DYNAMIC_RANK",
        "PE_DYNAMIC_QUARTILE",
        "PB_RATIO_RANK",
        "PB_RATIO_QUARTILE",
        "GROSS_MARGIN_RANK",
        "GROSS_MARGIN_QUARTILE",
        "NET_MARGIN_RANK",
        "NET_MARGIN_QUARTILE",
        "ROE_RANK",
        "ROE_QUARTILE",
        "TOTAL_MARKET_CAP_AVG",     # 行业平均总市值
        "NET_ASSETS_AVG",
        "NET_PROFIT_AVG",
        "PE_DYNAMIC_AVG",
        "PB_RATIO_AVG",
        "GROSS_MARGIN_AVG",
        "NET_MARGIN_AVG",
        "ROE_AVG",
        "INDUSTRY_COUNT"            # 行业成分股数量（用于排名显示）
    ]

    # 构造请求参数
    params = {
        "reportName": report_name,
        "columns": ",".join(columns),
        "filter": f'(SECUCODE="{secucode}")',
        "pageNumber": "1",
        "pageSize": "2",            # 返回两行：股票和行业平均
        "sortColumns": "",
        "source": "QuoteWeb",
        "client": "WEB",
        # "callback": f"jQuery{random.randint(1000000, 9999999)}_{int(requests.utils.time.time()*1000)}"
    }

    url = "https://datacenter-web.eastmoney.com/api/data/v1/get"

    try:
        response = requests.get(url, params=params, timeout=10)
        response.raise_for_status()

        # 解析 JSONP（去掉回调函数包裹）
        # jsonp_text = response.text
        # json_str = re.search(r'\(({.*})\)', jsonp_text, re.DOTALL).group(1)
        # data = json.loads(json_str)
        data = response.json()

        if data.get("code") != 0:
            print(f"接口返回错误: {data.get('msg')}")
            return None

        # 数据列表
        records = data.get("result", {}).get("data", [])
        if len(records) < 2:
            print("未找到行业平均数据")
            return None

        # 第一个是股票本身，第二个是行业平均
        stock_data = records[0]
        industry_avg_data = records[1]

        # 四分位等级映射（1-4 -> 中文）
        quartile_map = {1: "高", 2: "较高", 3: "较低", 4: "低"}

        # 整理输出结果
        result = {
            "股票": {k: stock_data.get(k) for k in columns if k in stock_data},
            "行业平均": {k: industry_avg_data.get(k) for k in columns if k in industry_avg_data},
            "排名信息": {
                "总市值": f"{stock_data.get('TOTAL_MARKET_CAP_RANK')}/{industry_avg_data.get('INDUSTRY_COUNT')}",
                "净资产": f"{stock_data.get('NET_ASSETS_RANK')}/{industry_avg_data.get('INDUSTRY_COUNT')}",
                "净利润": f"{stock_data.get('NET_PROFIT_RANK')}/{industry_avg_data.get('INDUSTRY_COUNT')}",
                "市盈率(动)": f"{stock_data.get('PE_DYNAMIC_RANK')}/{industry_avg_data.get('INDUSTRY_COUNT')}",
                "市净率": f"{stock_data.get('PB_RATIO_RANK')}/{industry_avg_data.get('INDUSTRY_COUNT')}",
                "毛利率": f"{stock_data.get('GROSS_MARGIN_RANK')}/{industry_avg_data.get('INDUSTRY_COUNT')}",
                "净利率": f"{stock_data.get('NET_MARGIN_RANK')}/{industry_avg_data.get('INDUSTRY_COUNT')}",
                "ROE": f"{stock_data.get('ROE_RANK')}/{industry_avg_data.get('INDUSTRY_COUNT')}",
            },
            "四分位属性": {
                "总市值": quartile_map.get(stock_data.get('TOTAL_MARKET_CAP_QUARTILE'), ""),
                "净资产": quartile_map.get(stock_data.get('NET_ASSETS_QUARTILE'), ""),
                "净利润": quartile_map.get(stock_data.get('NET_PROFIT_QUARTILE'), ""),
                "市盈率(动)": quartile_map.get(stock_data.get('PE_DYNAMIC_QUARTILE'), ""),
                "市净率": quartile_map.get(stock_data.get('PB_RATIO_QUARTILE'), ""),
                "毛利率": quartile_map.get(stock_data.get('GROSS_MARGIN_QUARTILE'), ""),
                "净利率": quartile_map.get(stock_data.get('NET_MARGIN_QUARTILE'), ""),
                "ROE": quartile_map.get(stock_data.get('ROE_QUARTILE'), ""),
            }
        }
        return result

    except Exception as e:
        print(f"请求失败: {e}")
        return None

if __name__ == "__main__":
    # 示例：获取东方财富（300059）的行业对比数据
    data = get_industry_compare("300059", market="1")  # 300059 在上海市场
    if data:
        print("===== 股票数据 =====")
        for k, v in data["股票"].items():
            print(f"{k}: {v}")
        print("\n===== 行业平均 =====")
        for k, v in data["行业平均"].items():
            print(f"{k}: {v}")
        print("\n===== 排名 =====")
        for k, v in data["排名信息"].items():
            print(f"{k}: {v}")
        print("\n===== 四分位属性 =====")
        for k, v in data["四分位属性"].items():
            print(f"{k}: {v}")