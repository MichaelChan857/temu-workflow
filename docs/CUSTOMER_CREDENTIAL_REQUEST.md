# 客户凭据申请表 — Temu API 生产接入

> 给客户运维 / 客户本人填,回填后即可切真实环境(预计 1 天内完成切换)。

## 一、客户先申请 (耗时 1-3 个工作日)

### 1. Temu Partner Platform 应用
- 入口: https://partner.temu.com (或当前最新 portal)
- 操作: **应用详情** → 拿到 `APP_KEY` 和 `APP_SECRET`
- **必填字段**:

| 字段名 | 值(示例) | 用途 |
|---|---|---|
| `APP_KEY` | `mxxxxxxxxxxxxxxxxxxxxxxxxxxxx` | API 调用身份 |
| `APP_SECRET` | `xxxxxxxxxxxxxxxxxxxxxxxxxxxxxxxx` | HMAC 签名 |

### 2. Temu 卖家授权 Token
- 入口: Partner Platform → **卖家授权** → 申请 access_token
- 必填字段:

| 字段名 | 值 | 用途 |
|---|---|---|
| `ACCESS_TOKEN` | (长字符串) | 调用授权 |

### 3. 卖家后台店铺信息
- 入口: Temu 卖家后台
- 必填字段:

| 字段名 | 值 | 用途 |
|---|---|---|
| `SHOP_ID` | `12345678` | 标识提交到哪个店铺 |
| `TARGET_SITE` | `US` / `UK` / `DE` / `FR` 等 | 目标国家(决定 API 区域) |

### 4. (可选但推荐) 沙箱 BASE
- 联系 Temu 技术支持申请 sandbox 环境
- 必填字段:

| 字段名 | 值 | 用途 |
|---|---|---|
| `SANDBOX_BASE` | `https://open-sandbox.temu.com/api` | 沙箱测试 |

### 5. 部署平台信息
- 选择一个:

  - [ ] **AWS** — Region + VPC + 子网 ID
  - [ ] **GCP** — Project + Zone + VPC network
  - [ ] **DigitalOcean** — Datacenter region + VPC
  - [ ] 其他:________

- 操作系统:推荐 **Ubuntu 22.04 LTS** 或 **Amazon Linux 2023**
- 实例规格:推荐 **4 vCPU / 8GB RAM / 40GB SSD**(单实例可承载 backend + n8n + postgres + redis)
- 公网 IP:必需(用于 webhook 回调 + API 出口)

### 6. SSL 证书
- 域名(用于 webhook 回调 HTTPS):`workflow.example.com`
- 证书:客户提供 / 我们用 Let's Encrypt 自动签

---

## 二、交付物时间表

| 时间 | 动作 | 谁 |
|---|---|---|
| T+0 | 客户开始申请 Temu 凭据 | 客户 |
| T+1-3 | 客户拿到凭据 → 填表回传 | 客户 |
| T+3 | 我们开始配置生产环境 | 我们 |
| T+3+0.5 天 | 切 sandbox 验证 | 我们 |
| T+3+1 天 | 切 live + 上线 | 我们 |

---

## 三、安全须知

1. **凭据不要通过邮件明文传**:用临时共享链接(1Password / Bitwarden Send)
2. **.env 不要 commit**:已在 `.gitignore`,部署时手动创建
3. **生产 SECRET_KEY 必须 32+ 字节随机**:`openssl rand -hex 32`
4. **生产数据库密码不要用 `temu_dev_only`**:文档里那个仅 dev 用

---

## 四、回填表(客户填完发回来)

```ini
# === Temu Partner Platform ===
TEMU_APP_KEY=___
TEMU_APP_SECRET=___
TEMU_ACCESS_TOKEN=___
TEMU_SANDBOX_BASE=https://open-sandbox.temu.com/api
SHOP_ID=___
TARGET_SITE=US

# === 部署平台 ===
DEPLOYMENT_PLATFORM=AWS  # AWS / GCP / DO / Other
DEPLOYMENT_REGION=ap-southeast-1
SSH_PUBLIC_KEY=ssh-ed25519 AAAA...

# === 域名 / SSL ===
DOMAIN=workflow.example.com
SSL_PROVIDER=lets-encrypt  # or own
```