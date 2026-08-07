# 配置与运行

## 1. Google Maps

在 Google Cloud 中启用 Maps Static API。把 Key 写入本机 `.env`，或设置为 GitHub Actions Secret：

- `GOOGLE_MAPS_API_KEY`

建议限制该 Key 的 API 范围和每日配额。地图会先下载为图片，再通过 Content-ID 内嵌到邮件，避免在邮件 HTML 中直接暴露 Key。

## 2. Gmail SMTP

建议使用专用 Gmail App Password，不要使用账号普通密码。需要：

- `SMTP_USER`
- `SMTP_APP_PASSWORD`
- `EMAIL_TO`

## 3. 数据文件

定时任务使用以下实际数据文件，并在成功发送后提交刷新结果作为下一轮比较基线：

- `data/sales_listings.json`
- `data/sales_new_build_candidates.json`
- `data/private_rentals.json`
- `data/cost_rental.json`

可以从对应的 `.example.json` 复制后更新。每条记录必须保留原始 URL 和 `verified_at`。

`sales_new_build_candidates.json` 是新房自动发现候选池：它保留已核验但未必进入当期邮件的项目，用于跨天去重、状态比较和每天限量加入。正式邮件仍只读取经过筛选的 `sales_listings.json`。

### 私人租赁发现

租赁刷新器使用公开 Daft.ie 与 Rent.ie 搜索页发现候选，并只接受可访问的具体详情页。商业平台可能使用动态渲染、速率限制或验证码；本项目不绕过访问控制。遇到此类限制时记录警告并保留可靠旧数据，不把搜索页或未核实候选写入正式邮件数据。

## 4. 本地测试

```bash
pytest -q
python scripts/refresh_rental.py --strict --discovery-limit 25 --max-new 8
python scripts/run_sales.py --data-file data/sales_listings.example.json
python scripts/run_rental.py \
  --rental-file data/private_rentals.example.json \
  --cost-rental-file data/cost_rental.example.json
```
