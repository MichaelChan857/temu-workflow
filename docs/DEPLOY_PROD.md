# 生产部署手册 — Temu Workflow (V1.x + V2.0)

> 适用:客户生产环境(海外云 + 真实 Temu 凭据)
> 预计部署时间:**1 个工作日**
> 前置条件:客户提供 5 项 Temu 凭据 + 部署平台已开通

---

## 第一步:准备工作(客户运维 / 我们)

### 1.1 申请 Temu 凭据
见 [`CUSTOMER_CREDENTIAL_REQUEST.md`](./CUSTOMER_CREDENTIAL_REQUEST.md)。客户填好后回填 5 项:

| 变量 | 值 |
|---|---|
| `TEMU_APP_KEY` | (客户提供) |
| `TEMU_APP_SECRET` | (客户提供) |
| `TEMU_ACCESS_TOKEN` | (客户提供) |
| `TEMU_SANDBOX_BASE` | `https://open-sandbox.temu.com/api` |
| `SHOP_ID` + `TARGET_SITE` | (客户提供) |

### 1.2 准备部署平台

**AWS EC2**(推荐):
```bash
# Region: ap-southeast-1 (新加坡,适合大陆商家跨境)
# Instance: t3.xlarge (4 vCPU / 16 GB RAM / 80 GB SSD)
# AMI: Ubuntu 22.04 LTS
# Security Group: open 22 (SSH) + 80/443 (web) from 0.0.0.0/0
# Elastic IP: 分配固定公网 IP
```

**GCP Compute Engine**:
```bash
# Region: asia-southeast1 / Zone: asia-southeast1-b
# Machine type: n2-standard-4 (4 vCPU / 16 GB)
# Image: ubuntu-2204-lts
# Firewall: allow 22 + 80 + 443
```

**DigitalOcean Droplet**:
```bash
# Region: SGP1 (新加坡)
# Size: s-2vcpu-8gb (4 vCPU / 8 GB / 80 GB SSD)
# Image: ubuntu-22-04-x64
# Firewall: inbound 22, 80, 443
```

### 1.3 DNS + SSL 准备
- 申请域名(cloudflare / 阿里云 DNS)
- 设置 A 记录: `workflow.example.com → <EIP/公网 IP>`
- SSL:推荐 Let's Encrypt 自动签(脚本见 §6)

---

## 第二步:服务器初始化(15 min)

SSH 上服务器后:

```bash
# 1. 更新系统
sudo apt update && sudo apt upgrade -y

# 2. 安装 Docker
curl -fsSL https://get.docker.com -o get-docker.sh
sudo sh get-docker.sh
sudo usermod -aG docker $USER
# 注销重登或新开 session

# 3. 安装 Docker Compose (v2)
sudo apt install docker-compose-plugin -y  # 或直接下 binary
docker compose version

# 4. 创建项目目录
sudo mkdir -p /opt/temu-workflow
sudo chown $USER:$USER /opt/temu-workflow
cd /opt/temu-workflow

# 5. 克隆代码
git clone https://github.com/<your-org>/temu-workflow.git .

# 6. 创建 secrets 目录(不进 git)
mkdir -p /opt/temu-workflow/secrets
chmod 700 /opt/temu-workflow/secrets
```

---

## 第三步:配置生产 .env(10 min)

**绝不要把 .env commit 进 git!** 用 `encrypt_env.py` 加密后入库。

### 3.1 创建明文 .env(仅本地,不入库)

```bash
cd /opt/temu-workflow

# 生成 32 字节随机 SECRET_KEY
SECRET_KEY=$(openssl rand -hex 32)
DB_PASSWORD=$(openssl rand -hex 16)
N8N_ENCRYPTION_KEY=$(openssl rand -hex 32)  # n8n 自己用

cat > .env <<EOF
# === 应用密钥 ===
SECRET_KEY=$SECRET_KEY
JWT_ALGORITHM=HS256
JWT_EXPIRE_HOURS=8

# === 数据库 ===
DATABASE_URL=postgresql+asyncpg://temu:$DB_PASSWORD@postgres:5432/temu_workflow

# === Redis ===
REDIS_URL=redis://redis:6379/0

# === Temu API 凭据(客户提供) ===
TEMU_USE_MOCK=false
TEMU_APP_KEY=<客户提供>
TEMU_APP_SECRET=<客户提供>
TEMU_ACCESS_TOKEN=<客户提供>
TEMU_SANDBOX_BASE=https://open-sandbox.temu.com/api
SHOP_ID=<客户提供>
TARGET_SITE=<US|UK|DE|...>

# === Temu 签名算法(联调后填) ===
# v1 / v2 / v3 — 默认 v2 通用算法
TEMU_SIGN_ALGO=v2

# === CORS ===
CORS_ORIGINS=https://workflow.example.com

# === N8N ===
N8N_HOST=workflow.example.com
N8N_PORT=5678
N8N_PROTOCOL=https
WEBHOOK_URL=https://workflow.example.com/
N8N_BACKEND_TOKEN=<登录 admin 拿后后填>
GENERIC_TIMEZONE=Asia/Shanghai
N8N_ENCRYPTION_KEY=$N8N_ENCRYPTION_KEY

# === 监控(可选) ===
SENTRY_DSN=
LOG_LEVEL=info
EOF

chmod 600 .env
echo ".env 已创建。DB_PASSWORD 已记录到 secrets/db_password.txt"
echo $DB_PASSWORD > secrets/db_password.txt
chmod 600 secrets/db_password.txt
```

### 3.2 加密入库(可选,但推荐)

```bash
# 本地用口令加密(适合无 KMS 的环境)
python backend/scripts/encrypt_env.py encrypt .env --out secrets/.env.enc
# 录入口令并妥善保存到 1Password / Bitwarden
# 然后删明文:rm .env

# 生产用 KMS(推荐)
export KMS_KEY_BASE64=$(aws secretsmanager get-secret-value --secret-id temu-workflow/env-key --query SecretString --output text | base64 -d | base64 -w0)
python backend/scripts/encrypt_env.py decrypt secrets/.env.enc --out .env
```

### 3.3 docker-compose.yml 覆盖

生产 compose 用 secrets mount,不用 env 直传:

```yaml
# docker-compose.prod.yml — 覆写原 docker-compose.yml
services:
  postgres:
    environment:
      POSTGRES_PASSWORD_FILE: /run/secrets/db_password
    secrets:
      - db_password

  backend:
    env_file: .env  # 或者用 docker secrets
    secrets:
      - db_password

  temu-adapter:
    env_file: .env

  n8n:
    image: temu-n8n:patched  # 用我们 patch 后的 image
    env_file: .env

secrets:
  db_password:
    file: ./secrets/db_password.txt
```

---

## 第四步:构建 patched n8n 镜像(10 min)

只有在我们 patch n8n(避开 isLeader bug)时需要。

```bash
cd /opt/temu-workflow

# 1. 构建 patched n8n image(在有外网的环境)
docker build -t temu-n8n:patched -f n8n/Dockerfile.patch n8n/

# 2. 导出 image 备份(可选)
docker save temu-n8n:patched -o temu-n8n-patched.tar
# 传到生产服务器:scp temu-n8n-patched.tar ubuntu@<server>:~/
# 生产服务器上:docker load -i temu-n8n-patched.tar

# 3. 验证 patch
docker run --rm temu-n8n:patched sh -c \
  'grep -c "PATCHED V2.0" /usr/local/lib/node_modules/n8n/dist/active-workflow-manager.js'
# 期望输出: 1 (或更多,表示 patch 已应用)
```

**生产可选方案**:**不用 patch image,直接用 n8nio/n8n:2.36.9**。等切到真实环境时,通过 **UI 触发 publish**(浏览器手动操作)。流程:
1. 部署完,SSH 进服务器
2. 浏览器访问 `https://workflow.example.com:5678`(需 NGINX 反代)
3. 用 owner 账号登录
4. 进入 workflow 编辑器 → 点右上角 **Active** toggle → 真正写入 `workflow_published_version`
5. **UI 操作完后 scheduleTrigger 才正常工作**

UI 操作代替 patch 是**长期可持续方案**(n8n 官方修复 PR #34382 merge 后就不用这步)。

---

## 第五步:启动整套服务(20 min)

```bash
cd /opt/temu-workflow

# 1. 启动(后台)
docker compose -f docker-compose.yml -f docker-compose.prod.yml up -d

# 2. 等服务健康(可能 30-60s)
docker compose ps
# 期望: postgres / redis / backend / temu-adapter / n8n 都 healthy / Up

# 3. 数据库迁移
docker compose exec backend alembic upgrade head

# 4. seed users(admin + 6 角色)
docker compose exec backend python scripts/seed_users.py

# 5. 导入示例数据(可选,客户生产通常不需要)
# docker compose exec backend python scripts/import_sample.py
```

---

## 第六步:NGINX 反代 + SSL(20 min)

```bash
# 1. 安装 NGINX
sudo apt install nginx -y
sudo systemctl enable nginx

# 2. 申请 SSL(Let's Encrypt)
sudo apt install certbot python3-certbot-nginx -y
sudo certbot --nginx -d workflow.example.com

# 3. NGINX 配置(默认 certbot 会创建,这里给完整版)
sudo tee /etc/nginx/sites-available/workflow <<'EOF'
upstream backend { server 127.0.0.1:8000; }
upstream n8n { server 127.0.0.1:5678; }
upstream temu_adapter { server 127.0.0.1:8001; }

server {
    listen 80;
    server_name workflow.example.com;
    return 301 https://$host$request_uri;
}

server {
    listen 443 ssl http2;
    server_name workflow.example.com;

    # SSL 由 certbot 自动管理

    # 前端业务 UI
    location / {
        proxy_pass http://backend;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # n8n UI
    location /n8n/ {
        proxy_pass http://n8n/;
        proxy_set_header Host $host;
        proxy_set_header Upgrade $http_upgrade;
        proxy_set_header Connection "upgrade";
        rewrite ^/n8n/(.*)$ /$1 break;
    }

    # n8n webhook callback
    location /webhook/ {
        proxy_pass http://n8n;
        proxy_set_header Host $host;
    }
}
EOF
sudo ln -sf /etc/nginx/sites-available/workflow /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```

---

## 第七步:Temu 凭据联调(30-60 min,最关键)

### 7.1 切 sandbox 验证

```bash
# 1. 在 backend 容器内调试
docker compose exec backend bash

# 2. 跑签名算法测试
python scripts/test_temu_signature.py

# 输出会告诉你:当前签名算法 (默认 v2) 是否被 Temu sandbox 接受
# 如果失败:在 .env 改 TEMU_SIGN_ALGO=v1 或 v3,重启 backend

# 3. 跑一次真实联调
python scripts/test_sandbox_publish.py
# 应该看到:{"success":true, "platform_product_id":"...", "platform_task_id":"..."}
```

### 7.2 切 live

```bash
# sandbox 验证通过后:
# 1. 改 .env:删除 TEMU_SANDBOX_BASE 行(或设为空)
# 2. 重启 backend
docker compose restart backend

# 3. 手动触发一次发布
docker compose exec backend python -c "
import asyncio
from app.adapters.temu_client import TemuAdapterClient

async def main():
    client = TemuAdapterClient()
    result = await client.publish_product(
        idempotency_key='live-test-001',
        shop_id='<SHOP_ID>',
        listing_snapshot={'title': 'Live test', 'price': 9.99, 'attributes': {}},
    )
    print(result)

asyncio.run(main())
"

# 4. 在 Temu 卖家后台核实商品是否上架
```

---

## 第八步:n8n workflow 配置(15 min)

切真实后,n8n workflow 的 token / URL 需更新:

```bash
# 1. admin 登录 n8n 拿 cookie
curl -X POST https://workflow.example.com/n8n/rest/login \
  -H "Content-Type: application/json" \
  -d '{"emailOrLdapLoginId":"admin@example.com","password":"<admin123>"}' \
  -c /tmp/n8n-cookies.txt

# 2. 验证 workflow 已 active
curl -X GET https://workflow.example.com/n8n/rest/workflows/temu-selection-daily-v1 \
  -b /tmp/n8n-cookies.txt | jq '.active'

# 3. 如果 scheduleTrigger 没激活:通过 UI 操作 publish 流程
#    浏览器:https://workflow.example.com/n8n → workflow 详情 → Active toggle
```

---

## 第九步:验证 + 告警(15 min)

### 9.1 端到端冒烟测试

```bash
# 跑集成测试(后端 API 链路)
docker compose exec backend python -X utf8 scripts/test_all_integration.py
# 期望:17/17 通过

# 跑 V2.0 端到端 demo
docker compose exec backend python -X utf8 scripts/demo_v20_full.py
# 期望:8 商品 → 30 天 → 校准 → Apply → 激活 → ALL OK
```

### 9.2 配置监控告警(可选)

- 接入 Sentry:填 `SENTRY_DSN` env
- 配置 CloudWatch / Stackdriver:看 `docker stats` 或安装 node-exporter
- 业务告警:通过现有 `/api/v1/alerts/send` 端点(已在 V1.0.0 实现)

---

## 第十步:日常运维

### 备份
```bash
# 数据库每日备份(已实现:scripts/backup_db.sh)
docker compose exec backend python scripts/backup_db.py
# 恢复:
docker compose exec backend python scripts/restore_db.py --file backups/2026-09-05.sql
```

### 升级
```bash
git pull
docker compose build backend temu-adapter
docker compose up -d backend temu-adapter
docker compose exec backend alembic upgrade head
```

### 排查
```bash
# 服务状态
docker compose ps

# 日志
docker compose logs -f backend --tail=100
docker compose logs -f temu-adapter --tail=100
docker compose logs -f n8n --tail=100

# n8n workflow 不跑?
# - 浏览器登录 n8n,看 workflow Active 状态
# - 看 execution_entity 表是否新行:docker compose exec postgres psql -U temu -d temu_workflow -c "SELECT COUNT(*) FROM execution_entity WHERE \"startedAt\" > NOW() - INTERVAL '1 hour';"
```

---

## 附录 A:凭据申请表
→ [`CUSTOMER_CREDENTIAL_REQUEST.md`](./CUSTOMER_CREDENTIAL_REQUEST.md)

## 附录 B:故障排查
→ [`RUNBOOK.md`](./RUNBOOK.md) — V1.0 已有的运维手册

## 附录 C:V2.0 业务闭环设计
→ [`V2_PLAN.md`](./V2_PLAN.md)

## 附录 D:n8n patch 说明
→ [`../n8n/Dockerfile.patch`](../n8n/Dockerfile.patch)
→ [`../n8n/imports/daily_sample.csv`](../n8n/imports/daily_sample.csv) — workflow 用的 CSV