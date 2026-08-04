# 南都柏林住房邮件统一标准

销售日报和租赁周报必须使用完整 HTML 邮件、内联 CSS 和同一套地图交付方式。任何关键检查失败时停止发送，不得降级成 Markdown、纯文本或无地图版本。

## 1. 标准主题

- 销售：`南都柏林住房销售｜YYYY-MM-DD`
- 租赁：`南都柏林住房租赁｜YYYY-MM-DD`
- 定时发送不得添加“测试”“补正版”“修正版”等后缀。
- 每次计划运行最多发送一封正式邮件。

## 2. 固定结构

1. 邮件标题。
2. `更新日期` 与真实的 `信息核验` 日期。
3. 单段 `本期重点`。
4. 三个摘要卡片：`本期条目`、`独立地图位置`、`当前重点`。
5. 地图颜色汇总。
6. `所有房源位置总览` 或 `所有出租位置总览`。
7. 正文中可见的 Google Static Maps 总览图。
8. 编号地点清单。
9. 分类房源卡片。
10. 每套房源的具体详情页与独立 Google Maps 链接。
11. Watchlist。
12. 状态与核验免责声明。

## 3. HTML 版式

- 页面背景：`#f3f5f8`。
- 主容器：白色背景、最大宽度约 `780px`、居中显示。
- 字体：`-apple-system, BlinkMacSystemFont, 'Segoe UI', Arial, sans-serif`。
- 主标题约 `28px`。
- `本期重点` 使用浅蓝背景、蓝灰边框和圆角。
- 三个摘要卡片使用兼容邮件客户端的 presentation table。
- 主要模块全部使用内联 CSS，不依赖外部 CSS 或 JavaScript。
- 房源必须使用独立圆角卡片，不能退化为连续纯文本。

## 4. Google 地图标准

地图必须同时提供：

1. 正文中可见的总览图。
2. 与总览标记一致的编号地点清单。
3. 每套房源的独立 Google Maps 地址链接。
4. 可点击的“在 Google Maps 中打开总览”按钮。

### 4.1 生成与内嵌

- 运行时使用 `GOOGLE_MAPS_API_KEY` 调用 Google Static Maps。
- 返回结果必须是 HTTP 200、图片 Content-Type 且内容非空。
- 图片保存为：
  - 销售：`output/sales_map.png`
  - 租赁：`output/rental_map.png`
- 最终邮件 HTML 不得包含 `maps.googleapis.com/maps/api/staticmap` URL。
- 最终邮件通过 CID 引用图片：
  - 销售：`src="cid:sales-map"`
  - 租赁：`src="cid:rental-map"`
- 邮件 MIME 必须使用 `multipart/related`，并附加对应的 `Content-ID` 图片。

### 4.2 显示格式

地图 `<img>` 必须保留：

- `width="640"`
- `display:block`
- `width:100%`
- `max-width:640px`
- `height:auto`
- `border:0`
- `border-radius:10px`

地图外层链接指向：

```text
https://www.google.com/maps/search/?api=1&query=...
```

### 4.3 禁止事项

- 不得只显示地点文字而没有地图。
- 不得只显示总览按钮而没有地图。
- 不得把远程 Static Maps URL直接放入邮件 `<img src>`。
- 不得在 HTML、日志、代码或文档中暴露 API key。
- 地图生成或 CID 附件校验失败时，不得继续发送。

## 5. 编号规则

- 编号使用 `1–9、A–Z`。
- 同一地址的多个户型共用一个编号。
- 地图、地点清单和详情卡片必须使用同一套编号。
- `独立地图位置` 显示去重后的地址数量。

## 6. 销售分类

- 绿色：Coming Soon。
- 蓝色：Affordable Purchase。
- 紫色：开发商和销售代理新房。
- 红色：私人二手出售房。
- 橙色：价格或状态变化。
- 灰色：Planning、Watchlist、已关闭或待核实。

房源卡片依次显示：编号与状态、名称、价格和户型、地址、说明、资格条件（如适用）、具体详情页和 Google Maps 链接。

## 7. 租赁分类

- 橙色：私人整租。
- 绿色：Cost Rental 当前开放。
- 灰色：Watchlist、已关闭或申请结束。

私人租赁卡片必须直达仍有效的具体房源详情页。搜索页、地区页和网站首页不得作为主要按钮。

## 8. 信息核验

- 只有成功访问并核验的来源才能更新 `verified_at`。
- 临时访问失败时保留原核验日期。
- 销售邮件显示真实范围，例如：`最新来源 2026-08-04；最旧记录 2026-07-26`。
- 不得仅修改邮件日期后重复发送旧数据。

## 9. 发送前自动校验

正式发送前必须全部通过：

- 数据文件存在且可解析。
- 测试通过。
- 详情链接符合要求。
- HTML 结构与内联样式完整。
- Google Static Maps PNG 已成功生成。
- HTML 使用正确 CID。
- CID 对应文件存在、非空且是有效图片。
- 最终 HTML 不含 Static Maps API URL。
- SMTP 登录预检通过。
- 主题符合标准。

实现位置：

- `dublin_house/maps.py`
- `dublin_house/emailer.py`
- `dublin_house/report_validation.py`
- `tests/test_email_map_contract.py`

任意一项失败都不得发送。
