# GLM Coding 订阅抢购完整 API 流程文档

> 基于抓包文件 `httpdata.json` 与项目源码（`app/services/payment_service.py`、`app/clients/bigmodel_client.py`、`app/clients/tencent_captcha_client.py` 等）整理。

---

## 1. 业务流程总览

从账号导入到生成支付二维码的完整链路如下：

```
1. 导入账号（bigmodel_token_production）
   ↓
2. GET /api/biz/customer/getCustomerInfo
   → 获取 customerNumber、organizations，自动选择默认 org/project
   ↓
3. POST /api/biz/pay/batch-preview
   → 获取套餐动态状态（售罄、禁止购买、是否已订阅等）
   ↓
4. 用户/配置选择 productId
   ↓
5. 验证码链路（自动）
   a. GET /cap_union_prehandle        → 获取 challenge sess / sid / 图片地址 / 提示文字
   b. GET /cap_union_new_getcapbysig  → 下载验证码图片
   c. 本地 OCR 识别点击点位
   d. GET /tdc.js + /ft.js            → 下载 TDC 指纹脚本
   e. Node VM 执行 TDC 采集 collect / eks
   f. POST /cap_union_new_verify      → 提交点击结果，获取 ticket / randstr
   ↓
6. POST /api/biz/pay/preview
   → 使用 ticket / randstr 获取 bizId（可竞速/可 ticket 池）
   ↓
7. POST /api/biz/pay/create-sign（新购）
   或 POST /api/biz/pay/product/update/sign（升级）
   → 获取支付链接 sign
   ↓
8. 本地生成二维码（sign → QR Code PNG）
   ↓
9. GET /api/biz/pay/check?bizId=...
   → 轮询支付状态 SUCCESS / EXPIRE / PENDING
```

---

## 2. 通用请求头

访问 BigModel API 时，必须携带以下请求头（由 `app/clients/bigmodel_client.py` 统一封装）：

| Header | 来源 | 说明 |
| --- | --- | --- |
| `Authorization` | `bigmodel_token_production` cookie 值 | JWT token，用户登录态 |
| `Bigmodel-Organization` | `getCustomerInfo.organizations[]` 默认选中 | 组织 ID |
| `Bigmodel-Project` | 默认组织下默认项目 | 项目 ID |
| `Accept-Language` | `zh` | 固定中文 |
| `Set-Language` | `zh` | 固定中文 |
| `Content-Type` | `application/json;charset=utf-8` | POST 请求必填 |
| `Referer` | `https://www.bigmodel.cn/glm-coding` | 部分接口会校验 |
| `User-Agent` | 账号级 browser_impersonate 对应 UA | 需与 TLS 指纹匹配 |

访问腾讯验证码接口时，关键请求头：

| Header | 说明 |
| --- | --- |
| `Referer` | `https://www.bigmodel.cn/glm-coding` |
| `Origin` | `https://turing.captcha.qcloud.com`（verify 用） |
| `Content-Type` | `application/x-www-form-urlencoded; charset=UTF-8`（verify 用） |
| `X-Requested-With` | `XMLHttpRequest`（verify 用） |

---

## 3. BigModel 上游 API

### 3.1 获取用户上下文

**请求**

```http
GET https://bigmodel.cn/api/biz/customer/getCustomerInfo?refer__1090={tracking_id}
```

**说明**

- 无需业务请求体，登录态由 `Authorization` 头提供。
- 用于确认 token 有效，并获取 `customerNumber`、组织/项目列表。

**关键响应字段**

| 字段 | 类型 | 用途 |
| --- | --- | --- |
| `customerNumber` | string | 后续 create-sign 的 `customerId` |
| `customerName` | string | 展示用 |
| `organizations[]` | array | 默认组织/项目选择 |
| `organizations[].id` / `organizationId` / `orgId` | string | 组织 ID |
| `organizations[].projects[]` / `projectList` / `projectVOList` | array | 项目列表 |
| `organizations[].projects[].id` / `projectId` | string | 项目 ID |
| `organizations[].projects[].projectType` | int | 优先选 `2` |
| `organizations[].projects[].isDefault` | bool | 默认项目标记 |
| `organizations[].isDefault` | bool | 默认组织标记 |

**默认选择逻辑**

- 组织：优先本地已保存 → 再 `isDefault=true` → 再第一个。
- 项目：优先本地已保存 → 再 `projectType=2` → 再 `isDefault=true` → 再第一个。

---

### 3.2 批量预览套餐

**请求**

```http
POST https://bigmodel.cn/api/biz/pay/batch-preview?refer__1090={tracking_id}
Content-Type: application/json;charset=utf-8

{
  "invitationCode": ""
}
```

**说明**

- `invitationCode` 可选，无邀请码传空字符串。
- 返回当前账号套餐售卖态，与前端静态套餐目录合并。

**关键响应字段**

| 字段 | 类型 | 用途 |
| --- | --- | --- |
| `isSubscribed` | bool | 是否已有订阅，决定走新购/升级 |
| `productList[]` | array | 动态套餐列表 |
| `productList[].productId` | string | 套餐 ID |
| `productList[].soldOut` | bool | 是否售罄 |
| `productList[].forbidden` | bool | 是否禁止购买 |
| `productList[].lastValid` | bool | 是否已有有效期内订阅 |
| `productList[].canRepurchase` | bool | 是否可续费 |
| `productList[].delay` | bool | 是否订阅变更类套餐 |
| `productList[].effectiveTime` | string | 生效时间 |
| `productList[].campaignDiscountDetails` | array | 优惠活动明细 |
| `productList[].monthlyRenewAmount` | string | 月均续费金额 |
| `productList[].monthlyOriginalAmount` | string | 月均原价 |

---

### 3.3 支付预览

**请求**

```http
POST https://bigmodel.cn/api/biz/pay/preview?refer__1090={tracking_id}
Content-Type: application/json;charset=utf-8
X-Request-Id: {uuid}
X-Timestamp: {unix_ms}

{
  "productId": "product-5643e6",
  "invitationCode": "",
  "ticket": "{tencent_captcha_ticket}",
  "randstr": "{tencent_captcha_randstr}"
}
```

**说明**

- `ticket` / `randstr` 必须来自腾讯验证码 verify 成功结果。
- `X-Request-Id` 与 `X-Timestamp` 在浏览器抓包中出现，后端未强制校验，但建议加上。

**关键响应字段**

| 字段 | 类型 | 用途 |
| --- | --- | --- |
| `bizId` | string | **核心字段**，支付签单与轮询都需要 |
| `thirdPartyAmount` | string | 实付金额，展示用 |
| `soldOut` | bool | 是否已售罄 |
| `originalAmount` | string | 订单原价 |
| `payAmount` | string | 套餐差价/续订差价 |
| `residualAmount` | string | 现有套餐剩余价值 |
| `giveAmount` | string | 赠金抵扣 |
| `cashAmount` | string | 现金抵扣 |
| `renewAmount` | string | 下次续费金额 |
| `campaignDiscountDetails` | array | 优惠明细 |
| `lastSubscriptionSummary` | object | 升级/变更场景需要 |
| `lastSubscriptionSummary.productId` | string | 升级时旧套餐 ID |
| `lastSubscriptionSummary.agreementNo` | string | 升级时协议号 |

**常见响应 code**

| code | 含义 |
| --- | --- |
| `200` + `bizId` | 成功 |
| `200` 无 `bizId` | 需要重试 |
| `555` | 系统繁忙，需重试 |
| `401` | ticket 过期或 token 失效 |

---

### 3.4 新购签单

**请求**

```http
POST https://bigmodel.cn/api/biz/pay/create-sign?refer__1090={tracking_id}
Content-Type: application/json;charset=utf-8

{
  "payType": "ALI",
  "productId": "product-5643e6",
  "customerId": "{customerNumber}",
  "bizId": "{preview.bizId}",
  "invitationCode": ""
}
```

**字段说明**

| 字段 | 来源 |
| --- | --- |
| `payType` | `ALI` 或 `WE_CHAT` |
| `productId` | 用户选择的套餐 |
| `customerId` | `getCustomerInfo.customerNumber` |
| `bizId` | `/biz/pay/preview` 返回 |
| `invitationCode` | 邀请码，可选 |

**关键响应字段**

| 字段 | 用途 |
| --- | --- |
| `sign` | 真实支付链接，用于生成二维码 |
| `orderId` | 支付单号，可选记录 |

---

### 3.5 升级签单

**请求**

```http
POST https://bigmodel.cn/api/biz/pay/product/update/sign?refer__1090={tracking_id}
Content-Type: application/json;charset=utf-8

{
  "payType": "ALI",
  "oldProductId": "{lastSubscriptionSummary.productId}",
  "newProductId": "product-5643e6",
  "customerId": "{customerNumber}",
  "agreementNo": "{lastSubscriptionSummary.agreementNo}",
  "bizId": "{preview.bizId}"
}
```

**说明**

- 仅当账号已有订阅（`isSubscribed=true`）时走升级链路。
- 依赖 `preview.lastSubscriptionSummary` 中的 `productId` 和 `agreementNo`。

---

### 3.6 支付状态检查

**请求**

```http
GET https://bigmodel.cn/api/biz/pay/check?bizId={bizId}&refer__1090={tracking_id}
```

**响应**

返回字符串或对象：

| 值 | 含义 |
| --- | --- |
| `SUCCESS` | 支付成功 |
| `EXPIRE` | 支付过期/二维码失效 |
| 其他 | 持续轮询 |

**建议**

- 轮询间隔约 1 秒。
- 增加超时上限（如 5 分钟）与主动取消能力。

---

### 3.7 其他订阅相关接口（抓包中可见）

| 接口 | 用途 |
| --- | --- |
| `GET /api/biz/subscription/v1-coding-plan-auto-renew-closed-by-system` | 查询自动续费关闭状态 |
| `GET /api/biz/subscription/enterprise/v2/pricing` | 企业版定价 |
| `GET /api/biz/subscription/enterprise/v2/subscription/detail` | 当前订阅详情 |
| `GET /api/biz/subscription/enterprise/v2/orders/pending` | 待支付订单 |
| `GET /api/biz/subscription/list` | 订阅列表 |
| `GET /api/biz/tokenResPack/productIdInfo` | token 资源包信息 |
| `GET /api/biz/customer/getTokenMagnitude?productId=...` | token 额度 |

> 这些接口主要用于页面展示与状态判断，不直接参与抢购主链路。

---

## 4. 腾讯验证码 API

### 4.1 预握手（prehandle）

**请求**

```http
GET https://turing.captcha.qcloud.com/cap_union_prehandle
    ?aid=196026326
    &protocol=https
    &accver=1
    &showtype=popup
    &ua={base64(user_agent)}
    &noheader=1
    &fb=1
    &aged=0
    &enableAged=0
    &enableDarkMode=0
    &grayscale=1
    &clientype=2
    &cap_cd=
    &uid=
    &lang=zh-cn
    &entry_url=https%3A%2F%2Fbigmodel.cn%2Fglm-coding
    &elder_captcha=0
    &js=%2FtgJCap.f0ca357b.js
    &login_appid=
    &wb=1
    &subsid=1
    &callback=_aq_{timestamp_ms}
    &sess=
```

**关键响应字段（JSONP）**

```json
{
  "sess": "s0...",
  "sid": "...",
  "data": {
    "dyn_show_info": {
      "bg_elem_cfg": {
        "img_url": "/cap_union_new_getcapbysig?..."
      },
      "instruction": "请依次点击：中 国 梦"
    }
  },
  "comm_captcha_cfg": {
    "tdc_path": "/tdc.js?app_data=...&t=...",
    "pow_cfg": {
      "prefix": "...",
      "md5": "..."
    }
  }
}
```

**说明**

- `sess` 是顶层 session，后续 verify 必须用这个 `sess`。
- `img_url` 里的 `sess` 与顶层 `sess` 不同，仅用于下载图片。
- `tdc_path` 用于下载 TDC 指纹脚本。
- `pow_cfg` 存在时需要计算 `pow_answer`。

---

### 4.2 下载验证码图片

**请求**

```http
GET https://turing.captcha.qcloud.com/cap_union_new_getcapbysig?img_index=1&image={image_key}&sess={image_sess}
```

**说明**

- 返回 PNG 图片字节。
- 图片中的文字/图标需要 OCR 识别点击坐标。

---

### 4.3 提交验证（verify）

**请求**

```http
POST https://turing.captcha.qcloud.com/cap_union_new_verify
Content-Type: application/x-www-form-urlencoded; charset=UTF-8

aid=196026326
&protocol=https
&sess={prehandle_sess}
&ans=[{"elem_id":1,"type":"DynAnswerType_POS","data":"251,254"},...]
&collect={TDC.getData(true) decoded}
&tlg={collect_length}
&eks={TDC.getInfo().info}
&pow_answer={prefix+suffix}
&pow_calc_time={ms}
```

**字段说明**

| 字段 | 来源 | 说明 |
| --- | --- | --- |
| `aid` | 固定 `196026326` | 腾讯验证码业务 ID |
| `protocol` | `https` | 固定 |
| `sess` | prehandle 顶层 `sess` | 注意不是图片 URL 里的 sess |
| `ans` | OCR 点位 | JSON 字符串，按点击顺序 `elem_id=1..N` |
| `collect` | `TDC.getData(true)` 后再 `decodeURIComponent` | 浏览器指纹采集串 |
| `tlg` | `collect` 解码后长度 | 字符串 |
| `eks` | `TDC.getInfo().info` | TDC 附加信息 |
| `pow_answer` | `prefix + suffix` | `md5(prefix+suffix) == target_md5` |
| `pow_calc_time` | 解 POW 耗时毫秒 | 数值型字符串 |
| `vData` | `window.getVData(queryString)` | 可选 |

**`ans` 单点格式**

```json
{
  "elem_id": 1,
  "type": "DynAnswerType_POS",
  "data": "251,254"
}
```

**关键响应字段**

| 字段 | 含义 |
| --- | --- |
| `ticket` | 验证票据 |
| `randstr` | 验证随机串 |
| `ret` | 结果状态 |
| `errorCode` / `errCode` | 错误码，`0`/`""` 表示成功 |
| `errorMessage` / `msg` | 错误信息 |
| `sess` | 新的 sess（可能更新） |

**错误码**

| errorCode | 含义 |
| --- | --- |
| `0` / 空 | 成功 |
| `50` | 识别失败，需要刷新重试 |
| 其他 | 按具体错误处理 |

---

### 4.4 TDC 脚本下载

**请求**

```http
GET https://turing.captcha.qcloud.com/tdc.js?app_data={app_data}&t={t}
GET https://turing.captcha.qcloud.com/ft.js
```

**说明**

- `tdc.js` 路径来自 prehandle 响应的 `comm_captcha_cfg.tdc_path`。
- `ft.js` 固定路径。
- 下载后由 Node VM 执行，产出 `collect` / `eks`。
- 本地会缓存到 `data/tdc_cache/`。

---

## 5. AegisFlow 本地后端 API

本地 FastAPI 服务统一以 `/api` 为前缀，前端 axios `baseURL=/api`。

### 5.1 健康与配置

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/healthz` | 健康检查（OCR/TDC/代理池状态） |
| GET | `/api/network-mode` | 当前网络出口模式 |
| PATCH | `/api/network-mode` | 切换网络出口模式 |
| GET | `/api/settings` | 获取全局设置 |
| PATCH | `/api/settings` | 更新全局设置 |

### 5.2 账号管理

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/accounts` | 账号列表 |
| POST | `/api/accounts/import` | 导入账号 |
| GET | `/api/accounts/{id}` | 账号详情 |
| PATCH | `/api/accounts/{id}` | 更新账号偏好设置 |
| DELETE | `/api/accounts/{id}` | 删除账号 |
| POST | `/api/accounts/{id}/bootstrap` | 同步账号上下文与套餐 |
| GET | `/api/accounts/{id}/products` | 获取套餐列表 |

### 5.3 验证码

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/api/accounts/{id}/captcha` | 手动提交 ticket/randstr |
| GET | `/api/accounts/{id}/captcha/challenge` | 获取验证码挑战（含 OCR 结果） |
| GET | `/api/accounts/{id}/captcha/tdc` | 采集 TDC collect/eks |
| POST | `/api/accounts/{id}/captcha/verify-payload` | 构造 verify payload |
| POST | `/api/accounts/{id}/captcha/verify` | 提交 verify |
| POST | `/api/accounts/{id}/captcha/solve` | 一键 solve（prehandle→OCR→TDC→verify） |

### 5.4 支付链路

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| POST | `/api/accounts/{id}/payments/preview` | 单路 preview |
| POST | `/api/accounts/{id}/payments/preview/seed` | 注入 preview 结果（调试） |
| POST | `/api/accounts/{id}/payments/qr` | 生成支付二维码 |
| POST | `/api/accounts/{id}/run` | 启动完整支付链路 |
| POST | `/api/accounts/{id}/probe` | 探测链路 |
| GET | `/api/accounts/{id}/payments/check/{biz_id}` | 查询支付状态 |

### 5.5 Ticket 池与任务

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/accounts/{id}/tickets` | 查看 ticket 池 |
| DELETE | `/api/accounts/{id}/tickets` | 清空 ticket 池 |
| POST | `/api/accounts/{id}/stock-monitor/start` | 启动库存监控 |
| POST | `/api/accounts/{id}/stock-monitor/stop` | 停止库存监控 |
| POST | `/api/accounts/{id}/pause` | 暂停当前任务 |
| GET | `/api/accounts/{id}/tasks` | 任务列表 |
| GET | `/api/accounts/{id}/tasks/{task_id}/qr.png` | 获取二维码 PNG |

### 5.6 日志

| 方法 | 路径 | 说明 |
| --- | --- | --- |
| GET | `/api/logs/streams` | 可用日志流 |
| GET | `/api/logs/today?stream=&account_id=&limit=` | 今日日志 |

---

## 6. 关键数据模型

### 6.1 账号导入请求

```json
{
  "label": "账号备注",
  "token": "bigmodel_token_production 的值",
  "cookie_header": "可选，原始 Cookie 字符串",
  "cookies": {
    "bigmodel_token_production": "..."
  },
  "org_id": "",
  "project_id": "",
  "invitation_code": "",
  "proxy_url": "",
  "user_agent": "",
  "browser_impersonate": ""
}
```

### 6.2 支付预览请求

```json
{
  "product_id": "product-5643e6",
  "invitation_code": "",
  "ticket": "",
  "randstr": ""
}
```

### 6.3 生成二维码请求

```json
{
  "product_id": "product-5643e6",
  "pay_type": "ALI",
  "biz_id": "",
  "invitation_code": ""
}
```

### 6.4 验证码 verify 请求

```json
{
  "sess": "",
  "points": [
    {"x": 251, "y": 254, "order": 1},
    {"x": 549, "y": 353, "order": 2},
    {"x": 55, "y": 352, "order": 3}
  ],
  "collect": "",
  "eks": "",
  "pow_answer": "",
  "pow_calc_time": 0,
  "vData": ""
}
```

---

## 7. 抢购策略说明

### 7.1 竞速模式（race preview）

- 配置 `preview_concurrency` 为 1~4。
- 每路并发独立循环：获取验证码 → verify → preview。
- 只要有一路拿到 `bizId`，立即停止其他路。
- 可配置 `preview_concurrency_time` 在指定时间统一发射 preview。

### 7.2 Ticket 池模式

- 配置 `ticket_pool_size > 0`。
- 先预收集 N 个未使用的 `ticket/randstr`。
- 到达并发时间后，按 `ticket_pool_drain_interval_ms` 配置串行或并行消耗 ticket 请求 preview。
- 池中 ticket 耗尽未拿到 bizId，自动回退到竞速模式。

### 7.3 签单重试

- 拿到 `bizId` 后，对当前 `bizId` 重试签单 3 次。
- 3 次均失败后，清空 preview，重新走完整 preview 链路拿新 `bizId`。

### 7.4 验证码重试

- OCR 点位少于 3 个或置信度不足：刷新验证码。
- verify 返回 `error=50`：刷新验证码。
- verify 其他失败：刷新验证码。
- preview 未拿到 `bizId`：重新获取验证码并重试。

---

## 8. 注意事项

1. **验证码 `sess` 不要混用**：verify 用 prehandle 顶层 `sess`，不是图片 URL 里的 `sess`。
2. **`ans` 是 JSON 字符串**：不是原生数组。
3. **`pow_answer` 必须带 prefix**：不只是 suffix。
4. **`tlg` 是 collect 解码后的长度**：不是固定值。
5. **OCR 坐标直接传原图坐标**：不需要再按前端缩放比例换算。
6. **ticket 不要复用**：每次 preview 前应使用新的 ticket/randstr。
7. **签单区分新购/升级**：根据 `batch-preview.isSubscribed` 判断。
8. **二维码直接用 `sign` 生成**：无需复刻 `/pay-middle-page` 的 AES 加密。
9. **代理池切换**：可在 Web 右上角切换本地/代理池出口模式。
10. **日志脱敏**：token/cookie/ticket/randstr/sign/collect/eks 等字段在结构化日志中会自动脱敏。

---

## 9. 静态套餐目录（v2）

| productId | 名称 | 周期 | 价格 |
| --- | --- | --- | --- |
| `product-02434c` | Lite | 月 | 49 |
| `product-1df3e1` | Pro | 月 | 149 |
| `product-2fc421` | Max | 月 | 469 |
| `product-b8ea38` | Lite | 季 | 132.3 |
| `product-fef82f` | Pro | 季 | 402.3 |
| `product-5d3a03` | Max | 季 | 1266.3 |
| `product-70a804` | Lite | 年 | 470.4 |
| `product-5643e6` | Pro | 年 | 1430.4 |
| `product-d46f8b` | Max | 年 | 4502.4 |
