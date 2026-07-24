# Dublin House 2026

南都柏林住房销售与租赁邮件监控项目。

项目包含两个相互独立、共享基础组件的任务：

- **南都柏林住房销售**：每天 08:00（Europe/Dublin）运行。
- **南都柏林住房租赁**：每周一 08:00（Europe/Dublin）运行。

销售和租赁邮件统一采用 **2026-07-24 09:13（Europe/Dublin）邮件版式**，详见 [邮件统一标准](docs/EMAIL_STANDARD.md)。缺少本期重点、摘要、Google Maps 总览入口、编号清单或房源独立地图链接时，正式发送会被阻止。

## 邮件内容

### 住房销售

- 本期重点
- Affordable Purchase
- 开发商新房
- 私人二手出售房
- Watchlist（Sale Agreed、申请关闭、资料待核实）
- Google Maps 总览入口、编号项目清单和每套房源的独立地图链接

### 住房租赁

- 本期重点
- Daft.ie 等可靠公开来源的私人整租
- 优先一室一厅整租和较低总月租
- Cost Rental 的公开资格、申请状态和具体官方项目页
- Google Maps 总览入口、编号项目清单和每套房源的独立地图链接
- 邮件不写入任何个人姓名、雇主或收入信息

## 快速开始

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

准备数据文件：

```bash
cp data/sales_listings.example.json data/sales_listings.json
cp data/private_rentals.example.json data/private_rentals.json
cp data/cost_rental.example.json data/cost_rental.json
```

生成本地 HTML：

```bash
python scripts/run_sales.py
python scripts/run_rental.py
```

发送邮件：

```bash
python scripts/run_sales.py --send
python scripts/run_rental.py --send
```

`--send` 会强制执行 09:13 基准版式、Google Maps 总览与独立地图链接、摘要字段和直达详情页校验。详细配置见 [docs/SETUP.md](docs/SETUP.md)，定时任务和 GitHub Actions 说明见 [docs/SCHEDULING.md](docs/SCHEDULING.md)。

## 安全说明

- Gmail App Password 等敏感信息只能放在 `.env` 或 GitHub Actions Secrets 中。
- 邮件地图采用普通 Google Maps Search 链接，不需要在邮件 HTML 中使用 Google Maps API Key。
- 项目不会绕过验证码、登录限制或商业平台的反自动化措施。
- 房源状态变化很快，邮件生成前应重新核实原始页面。
