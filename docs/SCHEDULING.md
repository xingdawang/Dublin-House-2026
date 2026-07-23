# 定时任务

仓库包含两个 GitHub Actions 工作流：

- `.github/workflows/sales.yml`
- `.github/workflows/rental.yml`

## 时间

GitHub Actions 的 cron 使用 UTC。为了兼容爱尔兰夏令时，工作流会在 UTC 07:00 和 08:00 都触发，再检查 `Europe/Dublin` 本地时间，只有本地 08:00 才真正发送。

- 销售：每天本地 08:00
- 租赁：每周一本地 08:00

## Secrets

在仓库 `Settings → Secrets and variables → Actions` 中配置：

- `GOOGLE_MAPS_API_KEY`
- `SMTP_USER`
- `SMTP_APP_PASSWORD`
- `EMAIL_TO`

## 数据更新

工作流不会绕过商业网站的反自动化措施。运行前需由合规数据流程更新三个实际 JSON 文件，或者在工作流前增加受授权的数据采集步骤。若实际数据文件不存在，工作流会停止，不会把示例数据当成真实房源发送。

## ChatGPT 定时任务

当前 ChatGPT 内建立的“南都柏林住房销售”和“南都柏林住房租赁”任务，与 GitHub Actions 相互独立。避免同时启用两套发送机制造成重复邮件。
