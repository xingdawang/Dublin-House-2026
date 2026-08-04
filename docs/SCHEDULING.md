# 定时任务

仓库包含两个正式 GitHub Actions 工作流：

- 销售：`.github/workflows/sales.yml`
- 租赁：`.github/workflows/rental.yml`

## 时间

两个工作流都使用 GitHub Actions 的时区感知调度：

```yaml
schedule:
  - cron: "0 7 ..."
    timezone: "Europe/Dublin"
```

因此不需要手工维护夏令时和冬令时两套 UTC cron。

| 任务 | Europe/Dublin 本地时间 | 频率 |
|---|---|---|
| 住房销售日报 | 07:00 | 每天 |
| 住房租赁周报 | 07:00 | 每周一 |

GitHub 计划任务可能因平台负载出现短暂排队，工作流的业务时间仍以 `Europe/Dublin` 为准。

## 手动触发

两个工作流都支持 GitHub Actions 页面中的 `workflow_dispatch`。

仓库还保留以下手动触发文件：

- `.github/manual-run/sales`
- `.github/manual-run/rental`

修改对应文件会触发相应工作流。不要同时通过多个入口触发同一个正式发送任务，以免重复邮件。

## Secrets

在仓库 `Settings → Secrets and variables → Actions` 中配置：

- `GOOGLE_MAPS_API_KEY`
- `SMTP_USER`
- `SMTP_APP_PASSWORD`
- `EMAIL_TO`

地图和邮件预检缺少任一必要 Secret 时会停止发送。

## 销售任务顺序

```text
baseline data
→ refresh and compare sources
→ pytest
→ HTML / CID map / SMTP preflight
→ send one email
→ persist refreshed source data
```

销售工作流具有 `contents: write` 权限，仅用于把成功刷新后的销售 JSON 提交回默认分支。

## 租赁任务顺序

```text
baseline data
→ pytest
→ validate live private listings
→ HTML / CID map / SMTP preflight
→ send one email
```

租赁任务当前尚未实现完整的自动发现和数据持久化。Codex 接手说明见 `docs/CODEX_HANDOFF.md`。

## 并发与失败策略

- 销售和租赁各自使用独立 concurrency group。
- 同一任务不会因为新运行开始而取消正在执行的正式发送。
- 工作流设置 25 分钟超时。
- 数据、测试、地图、CID、HTML 或 SMTP 任一硬性检查失败，任务停止且不发送邮件。

## 唯一正式调度源

GitHub Actions 是本仓库邮件发送的唯一正式调度源。不要同时启用另一套 ChatGPT、系统 cron 或本地 launchd 发送同一邮件，否则可能产生重复发送。
