# Clash Socks Server UI

把 `Clash 订阅 A` 和 `上游 Socks5 B` 组合成对外提供的 `Socks5 C`，并通过 WebUI 管理整个流程。

链路示意：

`客户端 -> 服务器 C -> Clash 订阅 A -> 上游 Socks5 B -> 目标网站`

## 一条命令部署

适用于全新的 Ubuntu 22.04 / 24.04 服务器。

```bash
curl -fsSL https://raw.githubusercontent.com/T-Chen-CN/Clash-Socks-Server-UI/main/bootstrap_ubuntu.sh | sudo bash
```

这条命令会自动完成：

- 安装 Python、venv、nginx 等依赖
- 从 GitHub 下载项目并部署到 `/opt/clash-socks-server-ui`
- 创建运行用户 `clashui`
- 生成随机的 WebUI 管理密码和 session secret
- 创建初始 `settings.json`
- 尝试预下载 `mihomo`
- 让 WebUI 运行在 `nginx` 后面
- 默认关闭 `/docs` 和 `/openapi.json`

部署完成后，脚本会直接打印：

- WebUI 访问地址
- 初始管理员账号
- 初始管理员密码
- 默认导出主机地址
- 默认可用的 C 端口池

## 部署后你只需要做什么

登录 WebUI 后，只需要做这几件事：

1. 录入 `Clash 订阅 A`
2. 录入 `上游 Socks5 B`
3. 刷新订阅
4. 启动默认路由

也就是说，不需要再手动改 `.env`、手动起服务、手动配反向代理。

## 默认访问方式

默认会同时监听：

- `http://服务器IP:18080/`
- `http://服务器IP/`

应用本体默认只监听本机：

- `127.0.0.1:18081`

也就是公网看到的是 `nginx`，不是直接暴露的 `uvicorn`。

## 可选环境变量

如果你想在执行一条命令时顺手改一些默认值，可以这样写：

```bash
curl -fsSL https://raw.githubusercontent.com/T-Chen-CN/Clash-Socks-Server-UI/main/bootstrap_ubuntu.sh | sudo env CSG_PUBLIC_HOST=1.2.3.4 CSG_PUBLIC_PORT=18080 bash
```

常用变量：

- `CSG_PUBLIC_HOST`
  用来覆盖自动探测到的公网 IP，决定默认导出的 `socks5://` 地址主机名。

- `CSG_PUBLIC_PORT`
  WebUI 对外端口，默认是 `18080`。

- `CSG_ENABLE_PORT_80`
  是否同时启用 `80` 端口，默认是 `1`。

- `CSG_ADMIN_USERNAME`
  初始管理员用户名，默认是 `admin`。

- `CSG_ADMIN_PASSWORD`
  初始管理员密码；如果不传，会自动生成随机值。

- `CSG_DEFAULT_ALLOWED_C_PORTS`
  默认允许分配的 C 端口池，默认是 `10808-10999`。

- `CSG_BASE_URL_OVERRIDE`
  用来覆盖默认的 `CSG_BASE_URL`。

- `REPO_REF`
  Bootstrap 使用的 Git 分支或 tag，默认是 `main`。

## 手动源码安装

如果你已经把仓库源码放到了服务器上，也可以在项目目录里执行：

```bash
sudo bash install_ubuntu.sh
```

它会执行和 bootstrap 相同的核心安装流程。

## 云防火墙和安全组

安装脚本能处理服务器内的服务和 `nginx`，但云平台控制台里的安全组仍然需要你自己确认。

至少建议放行：

- `18080/tcp`
- `80/tcp`
- 你实际要给客户端使用的 `Socks5 C` 端口，例如 `10808/tcp`

## HTTPS 说明

这个项目默认按“IP 直连 + nginx 反代”部署。

如果你要浏览器原生信任的 HTTPS，需要再绑定域名并为 `nginx` 或 `caddy` 配证书。没有域名时，可以正常使用 HTTP，但不会有受信任证书。

## 项目结构

- `app/main.py`：FastAPI 入口
- `app/gateway_multi.py`：`mihomo` 管理和链路逻辑
- `templates/`：WebUI 页面模板
- `static/`：前端静态资源
- `systemd/`：服务单元文件
- `nginx/`：反向代理示例配置
- `bootstrap_ubuntu.sh`：GitHub 一条命令部署入口
- `install_ubuntu.sh`：服务器上的实际安装器

## 安全建议

- 部署完成后及时保存脚本打印出的随机管理员密码
- 如果你手动指定了管理员密码，尽量不要使用弱密码
- 对公网开放的 `Socks5 C` 端口始终使用账号密码
- 尽量只开放你实际会使用的端口
- 如果要长期对外提供 WebUI，优先补上域名和 HTTPS
