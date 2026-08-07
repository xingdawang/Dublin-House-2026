# Codex 接手说明：住房销售日报与租赁周报

## 1. 当前状态

| 项目 | 销售日报 | 租赁周报 |
|---|---|---|
| 调度 | 每天 07:00 | 每周一 07:00 |
| 时区 | Europe/Dublin | Europe/Dublin |
| 工作流 | `.github/workflows/sales.yml` | `.github/workflows/rental.yml` |
| 命令入口 | `scripts/run_sales.py` | `scripts/run_rental.py` |
| 邮件模板 | `templates/sales_report.html.j2` | `templates/rental_report.html.j2` |
| 地图 PNG | `output/sales_map.png` | `output/rental_map.png` |
| 地图 CID | `sales-map` | `rental-map` |
| 主要数据 | `sales_listings.json`、`sales_insights.json`、`sales_new_build_candidates.json` | `private_rentals.json`、`cost_rental.json` |
| 自动刷新 | 已实现多来源新房项目发现、Daft 二手房发现、候选池和变化摘要 | 已实现 Daft.ie／Rent.ie 发现、变化比较、失效处理和持久化 |

## 2. 统一运行模型

```text
GitHub Actions schedule / manual dispatch
                │
                ▼
      检查实际数据文件存在
                │
                ▼
     来源刷新或有效性核验
                │
                ▼
             pytest
                │
                ▼
      生成 HTML + Static Map PNG
                │
                ▼
 HTML / 详情链接 / CID PNG / SMTP 预检
                │
                ▼
       multipart/related HTML 邮件
                │
                ▼
              Gmail
```

销售和租赁不得各自实现一套 SMTP 或地图附件逻辑。共享能力位于：

- `dublin_house/emailer.py`
- `dublin_house/maps.py`
- `dublin_house/report_validation.py`
- `dublin_house/models.py`
- `dublin_house/common.py`

## 3. 地图修复后的标准

此前邮件将 `maps.googleapis.com/maps/api/staticmap?...` 直接放入 `<img src>`。这种做法可能被邮件客户端代理、重写或阻止，也会让带 API key 的远程 URL进入邮件 HTML。

现在的标准流程是：

1. `create_map()` 调用 Google Static Maps 并下载 PNG。
2. PNG 写入 `output/sales_map.png` 或 `output/rental_map.png`。
3. `render()` 将模板上下文中的远程地图 URL替换为规范 CID。
4. HTML 使用 `cid:sales-map` 或 `cid:rental-map`。
5. `validate_inline_images()` 确认图片存在、非空且可识别。
6. `send_html()` 使用 `multipart/related` 添加相应 `Content-ID` 图片。
7. `validate_report_html()` 禁止最终 HTML 中出现 Static Maps API URL。

因此，Codex 后续不得恢复远程地图 `<img src>`。

## 4. 销售日报

### 执行顺序

```bash
python scripts/refresh_sales.py --strict --discovery-limit 8 --max-new 12 \
  --max-private 6 --max-apartment-only 1 \
  --max-new-build-projects 18 --max-new-build-additions 6 \
  --max-affordable-projects 4 --max-affordable-additions 2 \
  --min-new-build-sources 2
pytest -q
python scripts/run_sales.py --preflight
python scripts/run_sales.py --send
```

### 关键行为

- 对现有项目详情页进行核验。
- 从 Savills、Durkan、Evara、Hooke & MacDonald 和 Affordable Homes 公开目录自动发现新房项目；只接受核验成功的详情页。
- 新房范围覆盖指定的南都柏林偶数邮区及南部地名，跨来源去重并优先使用开发商官方页面。
- `sales_new_build_candidates.json` 保存完整候选池；邮件从中渐进加入项目，普通新房每轮最多 6 个、Affordable Purchase 每轮最多 2 个。
- 使用 Daft 逐区扫描 Dublin 2、4、6、6W、8、10、12、14、16、18、20、22、24 Houses，Daft 受限时使用 MyHome 公开结构化房源回退；搜索/结构化候选和最终详情页必须分开校验。
- 活跃二手房先跨邮区保留低价房源，再按全局低价补齐，去重后最多 6 套；Sale Agreed 等失效二手房排除；纯公寓项目最多保留 1 个。
- 日报优先持续跟踪开发商和销售代理的新房 House 项目，混合项目只有明确包含 House 户型时才作为住宅候选保留。
- 对比价格、卧室、浴室、房型和状态变化。
- 单个来源失败时保留上一轮数据及原核验日期。
- 全部来源都无法核验，或少于两个新房目录可访问，或没有任何南都柏林新房详情页核验成功时，`--strict` 失败并停止发送。
- 成功发送后，工作流将更新后的三份销售 JSON 提交回默认分支。

### 已知风险

- 页面导航、相关房源和历史成交文本可能干扰页面解析。
- 新增平台时必须使用详情页级测试样本，不能只测试搜索页。
- 任何状态识别都应尽量限定在当前房源的主信息区域。

## 5. 租赁周报

### 执行顺序

```bash
python scripts/refresh_rental.py --strict --discovery-limit 25 --max-new 8
pytest -q
python scripts/run_rental.py --preflight
python scripts/run_rental.py --send
```

### 关键行为

- 对每条私人房源进行最多三次详情页检查。
- 公开 Daft.ie 与 Rent.ie 搜索页用于发现候选，只接受具体详情页。
- 比较租金、卧室、浴室、房型、状态和最终 URL 变化。
- 404／410、搜索页重定向或正文明确失效的房源会从活跃私人租赁数据中移除。
- 单一来源临时失败时保留旧记录及原核验日期；所有私人详情页均无法核验时 `--strict` 失败。
- 发送前仍会重新核验详情页，失效链接不会进入正式邮件。
- 如果没有任何有效私人房源，整个任务失败。
- Cost Rental 按开放和 Watchlist 分类展示。
- 邮件按租金、户型匹配和区域偏好进行排序。
- 成功发送后，工作流提交更新后的私人租赁和 Cost Rental JSON。

### 访问限制与保守策略

实现文件：

```text
dublin_house/rental_refresh.py
scripts/refresh_rental.py
tests/test_rental_refresh.py
```

工作流顺序：

```text
refresh rental sources
→ test
→ validate live detail pages and preflight
→ send
→ commit refreshed data
```

商业平台的动态渲染、限流、验证码或反自动化响应一律视为来源失败；任务不会绕过访问控制。单一失败会保留可靠旧记录，但严格刷新无法核验任何私人详情页时必须停止。

## 6. 本地启动

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
```

`.env` 所需字段：

```text
GOOGLE_MAPS_API_KEY=...
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_USER=...
SMTP_APP_PASSWORD=...
EMAIL_TO=...
```

无 Secrets 时，可以使用示例数据生成 HTML，但无法完成 Static Maps 和 SMTP 预检。

## 7. Codex 推荐工作方式

1. 打开仓库后先阅读根目录 `AGENTS.md`。
2. 阅读本文件和 `docs/EMAIL_STANDARD.md`。
3. 执行 `pytest -q` 建立基线。
4. 每次只修改一个清晰问题。
5. 地图或邮件变更必须检查 MIME/CID 回归测试。
6. 只有用户明确要求时才发送邮件。
7. 发送后应核对 Gmail 中的最终 HTML，而不是仅看生成的本地文件。

## 8. 验收清单

- [ ] 销售每天 07:00，租赁每周一 07:00。
- [ ] 工作流使用 `timezone: Europe/Dublin`。
- [ ] 邮件主题没有测试或修正版后缀。
- [ ] HTML 是完整内联样式邮件。
- [ ] 总览地图在正文中可见。
- [ ] 地图使用正确 CID，并存在相应 MIME 图片附件。
- [ ] 最终 HTML 不包含 Google Static Maps API URL 或 key。
- [ ] 地图编号、图例、地点清单和房源卡片一致。
- [ ] 详情按钮直达具体项目或具体房源页。
- [ ] 任一硬性预检失败都会阻止发送。
