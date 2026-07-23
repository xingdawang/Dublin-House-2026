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

实际数据文件默认不提交到 Git：

- `data/sales_listings.json`
- `data/private_rentals.json`
- `data/cost_rental.json`

可以从对应的 `.example.json` 复制后更新。每条记录必须保留原始 URL 和 `verified_at`。

### Daft.ie

Daft.ie 是租赁任务的固定发现来源。商业平台可能使用动态渲染、速率限制或验证码；本项目不绕过访问控制。建议通过合规浏览、公开搜索结果或授权数据源发现候选房源，然后在写入 JSON 前打开原始页面核实价格、状态和整租属性。

## 4. 本地测试

```bash
pytest -q
python scripts/run_sales.py --data-file data/sales_listings.example.json
python scripts/run_rental.py \
  --rental-file data/private_rentals.example.json \
  --cost-rental-file data/cost_rental.example.json
```
