# AGENTS.md — Dublin House 2026

本仓库由 Codex 或其他代码代理接手时，必须遵守本文件。

## 1. 项目目标

维护两条独立但共享基础组件的住房邮件流水线：

| 流水线 | GitHub Actions | 时间（Europe/Dublin） | 邮件主题 |
|---|---|---|---|
| 住房销售日报 | `.github/workflows/sales.yml` | 每天 07:00 | `南都柏林住房销售｜YYYY-MM-DD` |
| 住房租赁周报 | `.github/workflows/rental.yml` | 每周一 07:00 | `南都柏林住房租赁｜YYYY-MM-DD` |

正式发送入口只能使用：

```bash
python scripts/run_sales.py --send
python scripts/run_rental.py --send
```

不要从临时脚本、Notebook、Gmail 网页或其他路径绕过预检直接发送。

## 2. 共享流水线合同

每次发送必须按以下顺序执行：

1. 检查实际数据文件存在。
2. 刷新或核验来源。
3. 运行 `pytest -q`。
4. 生成 HTML 和 Google Static Maps PNG。
5. 校验 HTML 结构、详情链接、地图 CID、PNG 内容和 SMTP 登录。
6. 仅在全部检查通过后发送一封正式邮件。
7. 需要时保存更新后的数据，作为下一轮比较基线。

任何关键步骤失败时必须停止发送，禁止降级成无地图、纯文本或旧数据邮件。

## 3. Google 地图硬性合同

地图问题是最高优先级回归项。

- Google Static Maps API URL 只用于运行时下载图片。
- API URL 和 API key 不得写入最终邮件 HTML。
- 销售地图文件：`output/sales_map.png`，CID：`sales-map`。
- 租赁地图文件：`output/rental_map.png`，CID：`rental-map`。
- HTML 必须使用：
  - `src="cid:sales-map"`，或
  - `src="cid:rental-map"`。
- 邮件 MIME 必须是 `multipart/related`，并包含对应 `Content-ID` 图片附件。
- 地图显示宽度固定为 `640`，同时保留 `width:100%`、`max-width:640px`、`height:auto`。
- 必须保留 Google Maps 总览按钮、颜色图例、编号地点清单和每套房源的独立地图链接。

相关实现：

- `dublin_house/maps.py`
- `dublin_house/emailer.py`
- `dublin_house/report_validation.py`
- `tests/test_email_map_contract.py`

## 4. 销售流水线

主要文件：

- 工作流：`.github/workflows/sales.yml`
- 刷新器：`dublin_house/sales_refresh.py`
- 刷新命令：`scripts/refresh_sales.py`
- 报告生成：`dublin_house/sales.py`
- 发送入口：`scripts/run_sales.py`
- 模板：`templates/sales_report.html.j2`
- 数据：`data/sales_listings.json`、`data/sales_insights.json`

硬性规则：

- 每日发送前必须刷新来源。
- 只有成功访问并核验的页面才能更新 `verified_at`。
- 单一来源临时失败时保留上一轮可靠记录和原核验日期。
- 全部来源都无法核验时停止发送。
- 不得把搜索结果页当成具体房源详情页。
- 自动发现的二手房当前以 Dublin 22、三居及以上、价格不高于 €425,000 为默认筛选。

## 5. 租赁流水线

主要文件：

- 工作流：`.github/workflows/rental.yml`
- 报告生成：`dublin_house/rental.py`
- 发送入口：`scripts/run_rental.py`
- 模板：`templates/rental_report.html.j2`
- 数据：`data/private_rentals.json`、`data/cost_rental.json`

硬性规则：

- 发送前必须逐条检查私人租赁详情链接仍然有效。
- 无效、重定向到搜索页或已失效的私人房源不得进入正式邮件。
- 至少保留一套有效私人整租；否则停止发送。
- Cost Rental 必须使用公开官方项目页或可靠直接项目页。
- 当前租赁数据尚未实现与销售同等级的自动发现和数据持久化；这是明确的后续改进项，不得假装已经完成。

## 6. Secrets

以下值只能存在于本地 `.env` 或 GitHub Actions Secrets：

- `GOOGLE_MAPS_API_KEY`
- `SMTP_USER`
- `SMTP_APP_PASSWORD`
- `EMAIL_TO`

不得在代码、测试、文档、提交信息或日志中写入真实值。

## 7. 修改后的最低验收

任何影响邮件、地图、来源刷新或工作流的改动，至少执行：

```bash
pytest -q
python scripts/run_sales.py --data-file data/sales_listings.example.json
python scripts/run_rental.py \
  --rental-file data/private_rentals.example.json \
  --cost-rental-file data/cost_rental.example.json
```

拥有本地 Secrets 时，再执行：

```bash
python scripts/run_sales.py --preflight
python scripts/run_rental.py --preflight
```

只有用户明确要求发送时才运行 `--send`。

## 8. 提交与分支

- 保持销售和租赁逻辑清晰分离，共享能力放入 `dublin_house/`。
- 不复制地图、SMTP、HTML 校验逻辑到两个脚本中。
- 用户明确要求直接使用默认分支时，可以提交到 `main`；不要为了形式创建无意义 PR。
- 每个提交只解决一个明确问题，提交信息说明业务结果。

## 9. 禁止事项

- 只修改邮件日期后重复发送旧数据。
- 地图失败后删掉地图继续发送。
- 将 Google Maps API URL 或 key 放进最终 HTML。
- 使用 Markdown 替代完整 HTML 邮件。
- 绕过验证码、登录限制、付费墙或反自动化措施。
- 自动发送“测试”“修正版”“补正版”等非标准主题。
- 在一次计划运行中发送多封正式邮件。
