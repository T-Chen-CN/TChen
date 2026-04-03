# Clash Socks Server UI

把 `Clash 订阅 A`、`上游 Socks5 B` 和服务器对外导出的 `Socks5 C` 放进同一个 WebUI 里统一管理。

它的目标不是替代完整的代理管理平台，而是把一台 Ubuntu 服务器上最常见、最容易出错的这条链路整理成一个可视化工作台：

`客户端 -> 服务器导出 C -> Clash 订阅 A -> 上游 Socks5 B -> 目标网站`

## 这个项目能解决什么问题

很多人已经有：

- 一份会变化的 `Clash` 订阅
- 一批需要轮换的 `Socks5` 落地
- 一台 Ubuntu 服务器

但实际落地时，往往会遇到这些麻烦：

- 每次换节点都要手改配置
- 多条路由同时运行时容易互相覆盖
- 不清楚当前到底是 A、B 还是 C 这一层出了问题
- `mihomo`、`systemd`、`nginx`、防火墙配置分散在好几个地方
- 新机器初始化时步骤多，容易遗漏安全设置

这个项目的价值，就是把这套流程收拢成一个更清晰的操作面板和一套更稳的部署默认值。

## 核心好处

- 让 `A / B / C` 三层关系更直观，不用长期靠手写 YAML 维持
- 支持多条路由并行运行，互不覆盖
- 可以分别测试 `A` 节点、`B` 落地和最终 `C` 导出，不再只能“整体坏了再猜”
- 导出标准 `socks5://user:pass@host:port` 链接，方便客户端直接导入
- 把部署默认值做得更安全：默认关闭 docs、默认反代、默认公网 Socks5 需要认证
- 对全新 Ubuntu 服务器提供“一条命令部署”的入口

## 适合谁

- 需要在自己的 Ubuntu 服务器上托管一套可视化代理导出面板的人
- 已经有 Clash 订阅和上游 Socks5 资源，但不想长期手改配置的人
- 需要同时维护多条“入口 A + 落地 B + 导出 C”线路的人
- 希望把部署、运行、诊断和导出整合到一起的人

## 不适合谁

- 需要企业级 RBAC、多管理员协作、审计日志或 SSO 的团队
- 需要一键式商业面板、用户计费、套餐管理的场景
- 需要跨发行版支持的人
- 不愿意自己处理云防火墙、安全组和基础 Linux 运维的人

目前项目主要面向：

- `Ubuntu 22.04 / 24.04`
- `amd64 / x86_64`

## 功能概览

- WebUI 登录与会话管理
- 共享 `A` 订阅录入、刷新、节点加载与测速
- 多路由 `B` 落地管理
- 每条路由独立的 `C` 监听口、认证信息和导出链接
- A / B / C 分层测试与诊断
- `mihomo` 自动下载、启动、停止、恢复
- 启动时清理残留进程并恢复已跟踪路由
- 默认通过 `nginx + systemd` 运行，而不是把 `uvicorn` 直接暴露到公网

## 工作原理

仓库里经常提到 `A / B / C`，这里统一说明一下：

- `A`
  你的 Clash 订阅，提供可选节点池。

- `B`
  你的上游落地 Socks5，通常是住宅代理或其他你已经持有的 Socks5 资源。

- `C`
  这台服务器对外提供的 Socks5 入口，客户端最终连接的是这一层。

- `路由`
  一条独立运行的组合配置，包含“当前选用的 A 节点 + 一组 B 落地 + 一组 C 导出参数”。

## 一条命令部署

适用于全新的 Ubuntu 22.04 / 24.04 服务器：

```bash
curl -fsSL https://raw.githubusercontent.com/T-Chen-CN/Clash-Socks-Server-UI/main/bootstrap_ubuntu.sh | sudo bash
```

部署脚本会自动完成：

- 安装 Python、venv、`nginx` 等依赖
- 从 GitHub 拉取源码到 `/opt/clash-socks-server-ui`
- 创建运行用户 `clashui`
- 生成随机管理员密码和 session secret
- 初始化 `settings.json`
- 尝试预下载 `mihomo`
- 配置 `systemd`
- 配置 `nginx` 反向代理
- 让应用只监听 `127.0.0.1:18081`
- 默认关闭 `/docs` 和 `/openapi.json`

脚本执行完后，会直接打印：

- WebUI 地址
- 初始管理员账号
- 初始管理员密码
- 默认导出主机地址
- 默认可用的 C 端口池
- 中英双语的防火墙端口提醒

安装过程中，脚本也会持续打印当前阶段，例如：

- 正在安装系统依赖
- 正在初始化应用配置
- 正在等待后端服务就绪
- nginx 是否已经正常工作

这样即使某一步耗时较长，也不容易误以为脚本已经卡死。

## 部署完成后你只需要做什么

进入 WebUI 之后，最常见的首次操作只有四步：

1. 录入 `Clash 订阅 A`
2. 录入 `上游 Socks5 B`
3. 刷新订阅并检查节点状态
4. 启动默认路由并复制 `C` 导出链接

也就是说，正常情况下你不需要再手动改 `.env`、手动写 `nginx` 配置，或者手动起 `uvicorn`。

## 文档导航

- [部署指南](docs/DEPLOYMENT.md)
- [使用指南](docs/USAGE.md)
- [架构说明](docs/ARCHITECTURE.md)
- [常见问题](docs/FAQ.md)
- [安全说明](SECURITY.md)

如果你是第一次接触这个项目，建议阅读顺序：

1. 先看这份 README
2. 再看 [部署指南](docs/DEPLOYMENT.md)
3. 然后看 [使用指南](docs/USAGE.md)
4. 最后把 [安全说明](SECURITY.md) 过一遍

## 常用部署变量

如果你希望在执行一条命令时顺手覆盖一些默认值，可以这样写：

```bash
curl -fsSL https://raw.githubusercontent.com/T-Chen-CN/Clash-Socks-Server-UI/main/bootstrap_ubuntu.sh | sudo env CSG_PUBLIC_HOST=1.2.3.4 CSG_PUBLIC_PORT=18080 bash
```

常用变量包括：

- `CSG_PUBLIC_HOST`
  覆盖自动探测到的公网 IP，用于生成默认导出地址。

- `CSG_PUBLIC_PORT`
  WebUI 对外端口，默认 `18080`。

- `CSG_ENABLE_PORT_80`
  是否同时启用 `80` 端口，默认 `1`。

- `CSG_ADMIN_USERNAME`
  初始管理员用户名，默认 `admin`。

- `CSG_ADMIN_PASSWORD`
  初始管理员密码；如果不传，会自动生成随机值。

- `CSG_DEFAULT_ALLOWED_C_PORTS`
  默认可分配的 C 端口池，默认 `10808-10999`。

- `CSG_BASE_URL_OVERRIDE`
  用来覆盖默认的 `CSG_BASE_URL`。

- `REPO_REF`
  Bootstrap 下载的分支或 tag，默认 `main`。

## 重要注意事项

- 云防火墙或安全组仍然需要你自己放行
- 没有域名时，默认是 `HTTP + nginx 反代`，不是受信任证书的 HTTPS
- 对公网开放的 `Socks5 C` 端口必须使用账号密码
- 这个项目不会替你处理云厂商控制台里的网络策略
- 当前部署体验主要针对 Ubuntu，其他发行版没有承诺

## 至少要放行哪些端口

- `18080/tcp`
- `80/tcp`
- 你实际打算开放的 `Socks5 C` 端口，例如 `10808/tcp`

## 项目结构

- `bootstrap_ubuntu.sh`
  一条命令部署入口，从 GitHub 下载源码并调用安装器。

- `install_ubuntu.sh`
  Ubuntu 上的实际安装器，负责依赖安装、环境初始化、`systemd` 和 `nginx` 配置。

- `app/main.py`
  FastAPI 入口和 API 路由。

- `app/gateway_multi.py`
  多路由 `mihomo` 管理、链路测试和运行时逻辑。

- `templates/`
  WebUI 模板文件。

- `static/`
  前端静态资源。

- `systemd/`
  服务单元文件。

- `nginx/`
  反向代理示例配置。

## 当前默认安全策略

这次版本的默认部署会尽量避免一些常见风险：

- 不再默认公网暴露 FastAPI docs
- 公网 Socks5 监听要求认证
- `uvicorn` 默认只监听本机
- `nginx` 负责公网入口
- 敏感配置和运行时文件权限更严格
- 启动时会清理残留 `mihomo` 进程并恢复已跟踪路由

更详细的安全说明请看 [SECURITY.md](SECURITY.md)。

## 你在 GitHub 页面上应该先看什么

如果你是：

- 第一次了解这个项目
  先看“这个项目能解决什么问题”和“适合谁”。

- 准备部署
  直接看 [部署指南](docs/DEPLOYMENT.md)。

- 已经部署完，准备开始录入资源
  直接看 [使用指南](docs/USAGE.md)。

- 担心公网暴露和口令问题
  直接看 [安全说明](SECURITY.md)。

- 排障中
  直接看 [常见问题](docs/FAQ.md)。
