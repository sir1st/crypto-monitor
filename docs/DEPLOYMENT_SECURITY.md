# ECS 公网部署与安全防护规范指南

本文档针对将 Vale Monitor 部署至公网 ECS 并通过 **Cloudflare Tunnel (cloudflared)** 暴露访问的生产场景，提供端到端的架构设计与安全硬化落地方案。

---

## 架构拓扑

```
[浏览器 / 客户端]
       │
       ▼ (HTTPS / WSS)
[Cloudflare Edge]
  ├─ 1. Zero Trust Access (邮箱 OTP 鉴权，会话 1 个月)
  ├─ 2. DDoS 防护 & WAF
  └─ 3. WebSocket 代理支持 (/ws)
       │
       ▼ (Cloudflare Tunnel 出站加密隧道，无需公网入站端口)
[ECS 内部 cloudflared]
       │
       ▼ (HTTP: 127.0.0.1:5000)
[Vale Monitor 服务 (非 root 用户 + systemd 守护)]
       │
       ▼ (只读 API 请求，带 ECS 出口固定 IP)
[交易所 (Binance / OKX / Bybit / Bitget / Gate)]
```

---

## 安全层级规范

### Level 1：基础设施与网络隔离（零暴露）

1. **ECS 安全组规则**：
   - **入站规则（Inbound）**：仅允许个人运维 IP 访问 SSH（TCP 22），**严禁放行 5000 端口或任何 Web 端口到 `0.0.0.0/0`**。
   - **出站规则（Outbound）**：全通（0.0.0.0/0），供 Cloudflare Tunnel 建立出站隧道及拉取交易所 API。
2. **应用监听配置**：
   - 保持应用环境配置中 `HOST=127.0.0.1`、`PORT=5000`，确保服务仅绑定在本地回环接口，不向公网监听。
3. **Cloudflare Tunnel (`cloudflared`) 配置**：
   - 安装 cloudflared：
     ```bash
     curl -L --output cloudflared.deb https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb
     sudo dpkg -i cloudflared.deb
     ```
   - 在 Cloudflare Zero Trust 控制台创建 Tunnel，或使用本地配置文件 `~/.cloudflared/config.yml`：
     ```yaml
     tunnel: <YOUR-TUNNEL-UUID>
     credentials-file: /etc/cloudflared/<YOUR-TUNNEL-UUID>.json

     ingress:
       - hostname: monitor.yourdomain.com
         service: http://127.0.0.1:5000
       - service: http_status:404
     ```
   - 注册并启动开机守护服务：
     ```bash
     sudo cloudflared service install
     sudo systemctl enable --now cloudflared
     ```

---

### Level 2：访问控制层（Cloudflare Zero Trust Access）

由于应用本身无内置登录与用户体系，访问鉴权直接托付给 Cloudflare Edge 网关层拦截。

1. **创建 Access Application**：
   - 登录 [Cloudflare Zero Trust 控制台](https://one.dash.cloudflare.com/)。
   - 导航至 **Access** -> **Applications** -> **Add an application** -> 选择 **Self-hosted**。
   - 配置 Application domain（如 `monitor.yourdomain.com`）。
2. **配置认证策略（Policy）**：
   - **Policy Name**：`Owner Only`
   - **Action**：`Allow`
   - **Session Duration（会话超时）**：设置为 **`1 month`（730 小时）**，一次验证可长期免密使用，兼顾高安全性与极佳使用体验。
   - **Include 规则**：
     - Selector：`Emails`
     - Value：填入个人的专属管理邮箱（例如 `your-email@domain.com`）。
3. **登录交互机制**：
   - 访问域名时，Cloudflare 会弹出验证界面并向指定邮箱发送 **6 位一次性验证码（OTP）**，验证通过后发放浏览器安全 Cookie，有效期 1 个月。
4. **WebSocket 支持（重要）**：
   - 导航至 Cloudflare 域名面板 -> **Network** -> 确认 **WebSockets** 开关处于 **Enabled** 状态（以保证 `/ws` 资产流式推送正常工作）。

---

### Level 3：交易所 API 资产保全底线

1. **权限严格最小化（Read-Only）**：
   - 在 Binance / OKX / Bybit / Bitget / Gate 创建 API Key 时：
     - ✅ **仅勾选**：读取 / 查询（Read / Query）权限。
     - ❌ **绝不勾选**：现货交易、合约交易（Trade / Spot / Futures）。
     - ❌ **绝不勾选**：提币、内部划转（Withdraw / Transfer）。
2. **绑定 ECS 固定出口公网 IP**：
   - 获取 ECS 出口 IP：
     ```bash
     curl -s ifconfig.me
     ```
   - 在各交易所 API 管理后台，将上述出口 IP 添加至 **受信任 IP / IP 白名单（Trusted IPs）**。
   - **作用**：即使 API 凭据在任何极端情况下泄露，攻击者也无法在非该 ECS 节点上发起任何 API 查询或调用。

---

### Level 4：ECS 主机权限与生产运行

1. **非 root 用户运行**：
   ```bash
   sudo useradd -m -s /bin/bash monitor
   sudo chown -R monitor:monitor /home/monitor/crypto-monitor
   ```
2. **SQLite 数据库文件权限加固**：
   - 数据库存储路径为 `./data/vale.db`，包含加密或脱敏后的配置信息：
     ```bash
     chmod 700 ./data
     chmod 600 ./data/vale.db
     ```
3. **Systemd 进程守护配置**：
   - 创建服务文件 `/etc/systemd/system/crypto-monitor.service`：
     ```ini
     [Unit]
     Description=Crypto Monitor Service
     After=network.target

     [Service]
     Type=simple
     User=monitor
     WorkingDirectory=/home/monitor/crypto-monitor
     ExecStart=/usr/bin/npm start
     Restart=always
     RestartSec=5
     Environment=NODE_ENV=production
     Environment=HOST=127.0.0.1
     Environment=PORT=5000

     [Install]
     WantedBy=multi-user.target
     ```
   - 编译构建并启动：
     ```bash
     npm run build
     sudo systemctl daemon-reload
     sudo systemctl enable --now crypto-monitor
     ```
