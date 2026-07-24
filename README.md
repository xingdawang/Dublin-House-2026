# Dublin House 2026

南都柏林住房销售与租赁邮件监控项目。

项目包含两个相互独立、共享基础组件的任务：

- **南都柏林住房销售**：每天 08:00（Europe/Dublin）运行。
- **南都柏林住房租赁**：每周一 08:00（Europe/Dublin）运行。

销售和租赁邮件使用同一套固定版式与发送门槛，详见 [邮件统一标准](docs/EMAIL_STANDARD.md)。地图缺失、摘要卡片缺失或链接不是具体详情页时，正式发送会被阻止，不会再发送残缺版本。

## 邮件内容

### 住房销售

- Affordable Purchase
- 开发商新房
- 私人二手出售房
- Watchlist（Sale Agreed、申请关闭、资料待核实）
- Google Static Maps 总览、编号、颜色图例和具体详情页直达链接

### 住房租赁

- Daft.ie 作为固定发现来源，并可补充其他可靠出租平台
- 优先一室一厅整租和较低总月租
- 公寓与 House 均可；位置稍远但租金明显更低的房源也会保留
- Cost Rental 单独展示公开资格、申请状态和具体官方项目页
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

`--send` 会强制执行地图、摘要卡片和直达链接校验。详细配置见 [docs/SETUP.md](docs/SETUP.md)，定时任务和 GitHub Actions 说明见 [docs/SCHEDULING.md](docs/SCHEDULING.md)。

## 安全说明

- API Key、Gmail App Password 等只能放在 `.env` 或 GitHub Actions Secrets 中。
- 生成的地图 URL 包含 Google Maps Key，因此不会提交到仓库。
- 项目不会绕过验证码、登录限制或商业平台的反自动化措施。
- 房源状态变化很快，邮件生成前应重新核实原始页面。