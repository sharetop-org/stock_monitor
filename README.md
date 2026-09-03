# stock-monitor

A股股票购买策略 + 价格监控预警系统。基于 **Python**，行情数据源为 **ShareTop**，通知渠道为**邮件**，运行方式为**定时轮询 + 回测器**。

## 特性

- **可配置化**：数据源、轮询间隔、自选股、启用的策略及参数、预警规则、通知渠道全部由 YAML 配置驱动，改配置即改行为，无需改动代码。
- **可扩展**：四大扩展点（数据源 / 交易策略 / 预警规则 / 通知器）都通过「抽象基类 + 注册表 + 配置注册」实现插件式接入。
- **定时轮询监控**：基于 APScheduler，按配置间隔拉取行情，逐股运行预警规则、产生并推送（邮件）预警。
- **回测器**：基于日 K 线对策略做历史回测，输出收益、年化、最大回撤、夏普、胜率与成交明细。
- **N日新低 / 新高监测报警**：触及 360/60 日等窗口的低点或 N 日新高即分别触发邮件提醒，附上市以来最高/最低价、相对历史高/低位的涨跌幅，以及实时总市值/流通市值/市盈率/市净率等估值字段。
- **「跌破N日新低买入 + 突破N日新高卖出」回测**：下跌分段累积建仓、冲高一次性清仓，输出总收益、XIRR 年化、胜率、盈亏比与每笔成交明细。

## 目录结构

```
stock-monitor/
├─ config/            # 全部可配置项（YAML）
│  ├─ settings.yaml     # 运行模式、轮询间隔、数据源、通知开关、回测参数
│  ├─ watchlist.yaml    # 自选股清单
│  ├─ strategies.yaml   # 启用的策略与参数
│  ├─ alerts.yaml       # 预警规则
│  └─ secrets.yaml      # 敏感信息（Token / SMTP 密码），已 gitignore，勿提交
├─ app/               # 核心代码
│  ├─ core/            # 数据结构、注册表、交易时段
│  ├─ datasource/      # 数据源抽象 + ShareTop 实现
│  ├─ indicators/      # 技术指标
│  ├─ strategy/        # 策略
│  ├─ alert/           # 预警规则 + 通知器
│  ├─ monitor/         # 轮询监控引擎（含低点监测 financial_monitoring_and_alerting.py）
│  ├─ strategy/        # 策略（含 N日新低回测 days_backtest.py）
│  └─ backtest/        # 回测引擎
├─ scripts/           # 可运行脚本（监控 / 回测 / 冒烟测试 / 新低·新高监测 / 新低回测）
├─ data/              # 数据缓存与回测结果（已 gitignore）
├─ logs/              # 运行日志（已 gitignore）
└─ tests/             # 单元测试
```

## 快速开始

### 1. 安装依赖

```bash
pip install -r requirements.txt
```

### 2. 配置

```bash
# 复制示例环境变量并在其中填入你的 Token 与通知凭据
copy .env.example .env
```

然后把股票代码填入 `config/watchlist.yaml`，按需调整 `config/settings.yaml` / `config/strategies.yaml` / `config/alerts.yaml`。

### 3. 先验证数据源

```bash
python scripts/test_source.py
```

### 4. 运行

```bash
# 回测某个策略（不联网通知，仅本地计算）
python -m app.cli backtest --strategy ma_cross --start 20250101 --end 20260831

# 启动定时监控（按 settings.yaml 的 interval 轮询 + 邮件预警）
python -m app.cli monitor

# 立即跑一次取价并检测预警（不上 scheduler）
python -m app.cli once
```

## 新增功能：N日新低/新高监测报警 & N日新低买入回测

> 若使用 conda 环境，执行前先激活：`conda activate py310`，或直接用其解释器
> `D:/software/miniconda3/envs/py310/python.exe scripts/... `。

### 1. N日新低 / 新高监测报警（`low-alert`）

股价跌破指定交易日窗口的低点、或创出 N 日新高时，通过项目统一通知器 [app/alert/notifier/mail_sender_new.py](app/alert/notifier/mail_sender_new.py) 的 `MailNew` 分别推送邮件。

- **低位报警**（触及 N 日新低）：含上市以来最高价与其日期、当前区间最低位相对历史高位的涨跌幅、触发日实时 `close`；
- **新高报警**（创 N 日新高）：含近 N 日高点、前一历史最高价与其日期、较前一历史最高的涨跌幅；
- 两类邮件都附实时行情接口里的总市值、流通市值、每股净资产、每股收益(TTM)、动态/静态/TTM市盈率、市净率、涨跌幅。低点与新高各自独立去重、分开发信。

```bash
# 一次性检查自选股（缺省 --symbols），读取watchlist.yaml里面的stocks配置文件，命中新低或新高即发邮件
python -m app.cli low-alert

# 指定股票、低位观察窗口、收件邮箱（新高按各股 high_days 或默认 1250）
python -m app.cli low-alert --symbols 600036.SH,600519.SH --windows 360,60 --to you@example.com

# 显式指定新高全局窗口（缺省 1250；传 0 关闭新高监测）
python -m app.cli low-alert --symbols 600036.SH --high-days 1250 --to you@example.com

# 用包装脚本（与上等价）
python scripts/run_low_alert.py --symbols 600036.SH,600519.SH --windows 360,60 --to you@example.com
```

| 参数 | 说明 |
|---|---|
| `--symbols` | 股票代码，逗号分隔；缺省取 `watchlist.yaml` 的低点/高点监测清单 |
| `--windows` | 低位全局兜底窗口（交易日天数），逗号分隔；未给该股配置时用此值 |
| `--high-days` | 高位全局兜底窗口（交易日天数），默认 `1250`；每股可在 `watchlist.yaml` 配 `high_days`；传 `0` 关闭新高监测 |
| `--to` | 收件邮箱；缺省取环境变量 `MAIL_ALERT_TO` |
| `--interval` | 轮询间隔秒，`0`=只跑一次（默认）；>0 时阻塞轮询 |

默认股票清单与窗口均来自 `watchlist.yaml`。low-alert 使用**独立清单**（新低与新高各自窗口，每股可单独配置）：
```yaml
stocks:
  - name: 贵州茅台
    ts_code: 600519.SH
    low_days: 250          # 仅监测 250 日低位（可选，单个窗口）
    windows: [250, 365]    # 或同时监测多个低位窗口，任一触发即报警
    high_days: 1250        # 监测 1250 日新高（可选，缺省 1250）
  - name: 平安银行
    ts_code: 000001.SZ     # 未配置 → 低位/高位都默认 1250（约5年）
```
低位窗口解析优先序：**该股 `low_days`/`windows` → 全局 `--windows` → 默认 1250**。
高位窗口解析优先序：**该股 `high_days` → 全局 `--high-days` → 默认 1250**。

发送前需在 `.env` / `config/secrets.yaml` 配置 ShareTop Token（`SHARETOP_TOKEN`）与邮箱发信凭据。

### 2. N日新低买入 / N日新高卖出回测（`low-backtest`）

策略口径：**跌破 N 日新低买入（越跌越买、持仓累加）**，可选 **突破 N 日新高一次性清仓**；输出总收益、XIRR 复合年化、胜率、盈亏比、最大回撤与每笔买入/成交明细。

```bash
# 只买不卖（新低累积，不结算胜率）
python -m app.cli low-backtest --symbols 600036.SH,600519.SH --low-days 250

# 新低买入 + 突破 N 日新高卖出（可算胜率/盈亏比）
python -m app.cli low-backtest --symbols 600809.SH --low-days 1250 --buy-amount 10000 --high-days 1250

# 用包装脚本
python scripts/run_low_backtest.py --symbols 600036.SH,600519.SH --low-days 250 --high-days 60
```

| 参数 | 说明 |
|---|---|
| `--symbols` | 股票代码，逗号分隔；缺省用自选股 |
| `--low-days` | 新低回看天数（交易日），默认 `1250`(≈5年)；跌破它即买入 |
| `--buy-amount` | 单次买入金额，默认 `10000`（买不起 1 手则硬买 1 手） |
| `--high-days` | 收盘价突破 N 日新高即卖出全部持仓（以统计胜率/盈亏比）；不传 = 只买不卖 |

## 数据来源：ShareTop（第三方 Python 包）

本项目行情数据来自第三方 Python 包 **`sharetop`**（需求文件 [requirements.txt](requirements.txt) 固定版本 `sharetop>=0.1.0`）。

`sharetop` 封装了 ShareTop 行情 API，提供 A 股历史 K 线、实时行情、上市公司信息、财务（分红/送转）等接口。项目统一通过 [app/datasource/sharetop_source.py](app/datasource/sharetop_source.py) 这一层接入：

- **客户端工厂**：`get_share_client()` 从本项目 `.env` 的 `SHARETOP_TOKEN` 读取鉴权 token，构建 `ShareTop` 客户端；
- **数据源类**：`ShareTopDataSource`（已注册为 `"sharetop"`）把原始应答归一化成项目内部结构（`Quote` / `KlineSeries`），并处理代码格式（`600519.SH`）、时间戳（秒/毫秒）等差异；
- 新低/新高监测与回测模块同样复用该工厂，避免散落重复建客户端。

```bash
# 安装
pip install sharetop --upgrade

# 冒烟测试数据源
python scripts/test_source.py
```

## ShareTop API 注意点（踩坑备忘）

- `get_history_data` 的**日线周期参数是 `'d'`，不是 `'1d'`**（传 `1d` 会返回“周期参数有误”）。
- **实时批量 K 线端点 `stockKline` 最多支持到 `120m`，不支持日线**；本项目在等日线时自动改用静态历史端点半逐只拉取。
- 实时行情的代码字段是 **`ts_code`**，价格是 **`close`**、昨收是 **`pre_close`**（不是 `last_price/prev_close`）。
- 时间戳单位不统一：**实时行情为秒、K 线为毫秒**，已做自动识别。
- 批量实时的 `stockCode` 返回形如 `SH600519`（交易所前缀 + 6 位），本项目统一归一化成 `600519.SH`。

## 排错：历史 K 线返回「权限不足」

**症状**：调用 `get_history_data`（历史日K静态接口）时，接口返回**字符串提示**而非数据——
>「当前权限无权访问该接口，请通过公众号『浔溯de小仓鼠』升级权限」

影响范围：`low-alert` 新低/新高监测与 `days_backtest` 新低回测，因为都靠历史K线判断"近 N 日新低/新高"。

**原因**：ShareTop **历史K线静态接口按账号权限限制**，与复权方式（`before`/`after`/`none`）无关；当前账号未授权该接口时统一返回如上提示。`low-alert` 对此已做**优雅降级**——视为「数据不足」(`insufficient`)，不会崩溃。

**解决**：按提示到公众号「浔海de小蔡仓」**升级权限**，生效后可跳过诊断：
```bash
D:/software/miniconda3/envs/py310/python.exe -c "
from app.monitor.financial_monitoring_and_alerting import get_client, check_low
r = check_low(get_client(), '600519.SH', [250])
print('status =', r['status'], '| 现价 =', r.get('latest_close'))
"
```
- `status` 为 `hit` / `no` 且带 `现价` → 权限已生效；
- 仍为 `insufficient` → 权限未同步或需换新 Token。

## 扩展指南

| 想加… | 步骤 |
|---|---|
| 新股票策略 | `app/strategy/` 新建一个继承 `BaseStrategy` 的类 → 在 `strategies.yaml` 注册并启用 |
| 新预警规则 | `app/alert/` 新建一个 `BaseAlertRule` 子类 → 在 `alerts.yaml` 注册 |
| 新通知渠道 | `app/alert/notifier/` 新建一个 `BaseNotifier` 子类 → 在 `settings.yaml` 启用 |
| 新数据源 | `app/datasource/` 新建一个 `BaseDataSource` 子类 → 在 `settings.yaml` 切换 |

详见各模块 docstring。

## 免责声明

本项目仅用于学习与技术验证，不构成任何投资建议。股市有风险，入市需谨慎。