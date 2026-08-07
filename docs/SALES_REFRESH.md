# 住房销售日报每日刷新要求

## 目标

销售日报不得仅修改邮件日期后重复发送旧数据。每次正式发送前，必须先重新读取公开来源，比较上一轮数据，并将真实核验结果写入邮件。

## 固定执行顺序

1. 读取上一轮 `data/sales_listings.json` 和 `data/sales_insights.json`。
2. 逐条访问已跟踪项目的原始详情页。
3. 从开发商、销售代理、Affordable Homes 目录发现新房项目，并从市场搜索页发现符合条件的二手房。
4. 比较价格、卧室数、房型和销售/申请状态。
5. 新增符合条件的房源；Sale Agreed、Sold 或失效的二手房从报告移除，失效新房项目可转入 Watchlist；临时访问失败时保留上一轮可靠记录及原核验日期。
6. 生成自动刷新摘要，写明检查数量、成功核验数量、新增、变化和失败来源。
7. 运行测试、地图生成、邮件结构检查和 SMTP 登录预检。
8. 只有全部强制检查通过后才发送邮件。
9. 发送成功后，将更新后的销售数据提交回默认分支，作为下一轮比较基线。

## 来源优先级

- 一级：政府、地方议会、Affordable Homes、开发商和销售代理官方项目页。
- 二级：Daft、MyHome 等公开房源平台的具体详情页。
- 新房发现入口：Savills New Homes、Durkan、Evara、Hooke & MacDonald、Affordable Homes Ireland 的公开目录。
- 二手房发现入口：Daft Dublin 2、4、6、6W、8、10、12、14、16、18、20、22、24 Houses 逐区搜索；Daft 受限的邮区使用 MyHome 公开结构化房源回退。

## 入选规则

- Affordable Purchase、Coming Soon、新房项目继续按项目状态跟踪。
- 新房区域覆盖 Dublin 2、4、6、8、10、12、14、16、18、20、22、24，以及 Adamstown、Lucan、Tallaght、Cherrywood、Shankill、Kilternan、Stillorgan 等南部区域。
- 目录页只产生候选；必须成功访问具体项目详情页、通过南都柏林和新房证据检查后才可入库。
- 新房候选跨来源按项目名称去重，开发商官方详情页优先于销售代理详情页。
- 活跃普通新房最多保留 18 个，每轮最多新加入 6 个；Affordable Purchase 最多保留 4 个，每轮最多新加入 2 个。
- 二手房同等扫描 12 个指定邮区，先在每个有效邮区保留最低价候选，再按全局低价补齐。
- 自动发现的二手房默认筛选：三居及以上、挂牌价不高于 €425,000。
- 搜索页每区最多检查 8 个详情链接，全局每天最多吸收 12 个新候选；最终邮件最多保留 6 套活跃二手房。
- Sale Agreed、Offer Accepted、Sold、Unavailable 的二手房不进入报告。
- House 项目优先，纯公寓最多保留 1 个，但公寓和二手房都不会被完全排除。

## 核验日期规则

- 只有页面成功访问并通过详情页校验，才更新该记录的 `verified_at`。
- 页面临时超时、限流或拒绝访问时，不得把 `verified_at` 改成当天。
- 邮件必须显示真实范围：`最新来源 YYYY-MM-DD；最旧记录 YYYY-MM-DD`。
- 全部来源均无法核验时，刷新步骤失败并阻止发送。
- 严格模式下至少两个新房目录可访问、至少一个南都柏林项目详情页核验成功，且至少一个二手邮区搜索可访问；否则停止发送。

## 容错与安全

- 不绕过验证码、登录限制、付费墙或平台反自动化措施。
- 单一来源临时失败不会删除上一轮可靠房源，也不会伪造当天核验结果。
- HTTP 404 或明确失效的二手详情页从报告移除；新房项目可转入 Watchlist。
- Google Maps API Key、SMTP 凭据和收件人仅从 GitHub Secrets 读取，不写入数据或邮件正文。

## 命令

```bash
python scripts/refresh_sales.py --strict --discovery-limit 8 --max-new 12 \
  --max-private 6 --max-apartment-only 1 \
  --max-new-build-projects 18 --max-new-build-additions 6 \
  --max-affordable-projects 4 --max-affordable-additions 2 \
  --min-new-build-sources 2
python scripts/run_sales.py --preflight
python scripts/run_sales.py --send
```
