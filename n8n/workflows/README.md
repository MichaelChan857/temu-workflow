# n8n 工作流说明

## 工作流列表

| 文件 | 用途 |
|---|---|
| `temu-selection-daily.json` | 每日定时选品：读 CSV → 标准化 → 调后端 → 告警/通知 |

## 导入方式

1. 打开 n8n UI：http://localhost:5678
2. Workflows → Import from File → 选择 `temu-selection-daily.json`

## 环境变量

n8n 容器需要以下环境变量（在 docker-compose 中已默认设置）：

| 变量 | 用途 |
|---|---|
| `N8N_BACKEND_TOKEN` | n8n 调后端用的 bearer token（与服务端 JWT_SECRET 解出的 token 对应） |

## 工作流节点

```
触发(每天 06:00) → 读 CSV → 解析 → 调 /api/v1/import/json → 候选不足？ 
                                                          ├─ 是 → 发送告警
                                                          └─ 否 → 通知一审
```

## 测试方式

不启动 n8n UI 也可测试，参见：
```bash
python scripts/test_workflow_e2e.py
```