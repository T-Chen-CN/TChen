# Clash Socks Server UI

一个面向 Ubuntu / Linux 服务器的远程 WebUI，用来把：

- `Clash 订阅 A`
- `住宅 Socks5 落地 B`

组合成对外可直接使用的 `Socks5 C`。

最终链路如下：

```text
外部设备 -> 服务器上的 Socks5 C -> 订阅 A 中转 -> 落地 B -> 目标网站
```

项目已经内置完整的 Web 管理界面，可远程完成订阅录入、路由管理、落地录入、节点切换、批量测速、出口 IP 检测和 C 链接导出。

## 核心能力

- 共享订阅 A 管理
  - 录入 Clash 订阅
  - 独立加载和缓存 A 节点
  - 单点测速、批量测速、节点切换
- 多路由 B / C 管理
  - 一个 A 对应多条 B
  - 多个 C 可同时运行
  - 路由级独立监听端口、账号、密码、控制器端口
- 出口连通性与属性检测
  - 测试 B 落地直连可用性
  - 测试最终 C 对外可用性
  - 查询出口 IP、位置、网络类型、运营商等摘要信息
- 服务器侧自动化
  - 自动下载 / 更新 `mihomo`
  - 自动生成配置并启动进程
  - 提供 `systemd` 服务文件与 `nginx` 反代示例
- WebUI 运维能力
  - 登录鉴权
  - 仪表盘总览
  - B 落地列表
  - C 输出列表
  - 路由日志查看

## 适用场景

- 需要把多个住宅 Socks5 落地统一发布为对外可用的 Socks5 链接
- 需要在服务器上集中管理 A 节点和多条 B / C 路由
- 需要给外部设备直接分发 `socks5://user:pass@host:port` 链接
- 需要快速判断哪些路由已经可公网使用

## 技术栈

- Backend: `FastAPI`
- Frontend: `Jinja2 + Vanilla JavaScript + CSS`
- Proxy Core: `mihomo`
- Process / Service: `systemd`
- Optional Reverse Proxy: `nginx`

## 页面结构

- `仪表盘`
  - 查看共享订阅 A、B 摘要、C 摘要和整体可用性
- `Ai订阅管理`
  - 保存订阅、加载 A 节点、缓存节点、测速、切换节点
- `B落地列表`
  - 维护每条路由的 B 信息并测试直连
- `C输出列表`
  - 设置 C 输出格式、批量运行、批量测试、复制完整链接
- `设置`
  - 统一维护导出地址、端口池、运行参数等全局配置

## 目录结构

```text
ClashSocksServerUI/
├─ app/
│  ├─ auth.py
│  ├─ config.py
│  ├─ gateway.py
│  ├─ gateway_multi.py
│  └─ main.py
├─ nginx/
│  └─ clash-socks-webui.conf.example
├─ static/
│  ├─ app.js
│  └─ style.css
├─ systemd/
│  └─ clash-socks-webui.service
├─ templates/
│  ├─ index.html
│  └─ login.html
├─ .env.example
├─ install_ubuntu.sh
└─ requirements.txt
```

## 快速开始

### 1. 本地开发

```bash
python -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
cp .env.example .env
uvicorn app.main:app --reload --host 0.0.0.0 --port 18080
```

打开：

```text
http://127.0.0.1:18080/login
```

### 2. Ubuntu 服务器部署

将项目上传到服务器后执行：

```bash
sudo bash install_ubuntu.sh
```

然后完成：

1. 编辑 `/opt/clash-socks-server-ui/.env`
2. 启动服务

```bash
sudo systemctl start clash-socks-webui
sudo systemctl status clash-socks-webui
```

### 3. 服务器放行

至少需要放通：

- WebUI 端口，例如 `18080/TCP`
- 对外发布的 Socks5 端口，例如 `10808-10999/TCP`

如果需要域名 / HTTPS，可参考：

- `nginx/clash-socks-webui.conf.example`

## 环境变量

`.env.example` 中包含基础运行配置：

| 变量 | 说明 |
| --- | --- |
| `CSG_HOST` | WebUI 监听地址 |
| `CSG_PORT` | WebUI 监听端口 |
| `CSG_APP_NAME` | 页面显示名称 |
| `CSG_ADMIN_USERNAME` | 管理员用户名 |
| `CSG_ADMIN_PASSWORD` | 管理员密码 |
| `CSG_SESSION_SECRET` | Session 密钥 |
| `CSG_BASE_URL` | 可选，外部访问基地址 |
| `CSG_TEST_URL` | 默认测试 URL |
| `CSG_TEST_TIMEOUT_MS` | 默认测试超时 |

## 运行逻辑

### A 订阅

- 订阅保存后，A 节点可独立载入并缓存
- 未手动刷新前，页面优先展示缓存节点
- 只有点击“刷新订阅 A”时才重新拉取远端订阅

### B 落地

- 每条路由单独保存一条 B
- 支持常见带认证的 Socks5 录入格式
- 可测试 B 直连可用性和出口 IP 摘要

### C 导出

- 每条路由独立生成一个公网可用的 Socks5 C
- 支持多种 C 输出格式切换
- 可批量运行、批量测试、批量复制

## 安全建议

- 首次部署后立刻修改 WebUI 管理员密码
- 不要在公网环境继续使用默认示例账号密码
- 对外开放的 Socks5 端口尽量使用高位端口池
- 优先给 WebUI 添加 HTTPS
- 尽量通过云防火墙限制来源 IP
- 不要把 `.env`、`data/`、`runtime/`、`logs/` 提交到仓库

## 已忽略的运行文件

仓库默认不会提交这些内容：

- `.env`
- `.venv/`
- `data/`
- `runtime/`
- `logs/`
- `__pycache__/`

## 许可证

本项目默认以 [MIT License](./LICENSE) 发布。
