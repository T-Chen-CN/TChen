# 部署指南

这份文档专门说明如何把项目部署到一台全新的 Ubuntu 服务器上，以及部署后你还需要自己确认哪些事项。

## 支持环境

- Ubuntu 22.04 / 24.04
- `amd64 / x86_64`
- 具备公网访问能力的服务器
- 能够使用 `sudo`

当前脚本默认围绕 Ubuntu 编写，不承诺在 Debian、CentOS、AlmaLinux 或容器环境里无改动可用。

## 推荐部署方式

推荐直接使用 bootstrap：

```bash
echo "[1/2] Downloading bootstrap script from GitHub..." && curl -fL --retry 3 --connect-timeout 15 --max-time 300 https://raw.githubusercontent.com/T-Chen-CN/Clash-Socks-Server-UI/main/bootstrap_ubuntu.sh -o /tmp/clash-socks-bootstrap.sh && echo "[2/2] Starting installer..." && sudo bash /tmp/clash-socks-bootstrap.sh; rm -f /tmp/clash-socks-bootstrap.sh
```

这条命令会先明确打印“正在下载”和“开始安装”，下载阶段也会显示更正常的 `curl` 进度信息。相比完全静默的 `curl -fsSL ... | sudo bash`，它更容易判断当前是“正在下载”还是“已经开始安装”。

这会自动执行：

- 下载仓库源码
- 安装依赖
- 创建运行用户
- 初始化 `.env`
- 启动 `systemd`
- 配置 `nginx`
- 尝试预装 `mihomo`

## 一条命令部署前的建议检查

- 确认这是一台 Ubuntu 服务器
- 确认云安全组允许你后续开放 `18080/tcp`、`80/tcp` 和业务需要的 `Socks5 C` 端口
- 确认你有服务器公网 IP
- 确认你可以保存脚本打印出来的随机管理员密码

## 脚本完成后会发生什么

默认行为如下：

- 项目被安装到 `/opt/clash-socks-server-ui`
- 应用由 `systemd` 托管
- `uvicorn` 监听 `127.0.0.1:18081`
- `nginx` 对外监听 `18080`，并可同时监听 `80`
- docs 和 openapi 默认关闭
- 默认管理员账号为 `admin`
- 默认管理员密码自动随机生成
- 默认导出地址会尽量使用探测到的公网 IP
- 安装过程会持续打印当前阶段状态，避免误判为卡死
- 安装结束时会双语提醒需要开放的 WebUI 和 C 端口

## 首次部署后应该立刻确认的事情

### 1. 打开 WebUI

默认访问方式：

- `http://服务器IP:18080/`
- `http://服务器IP/`

### 2. 保存安装脚本打印出的管理员密码

部署脚本只会在执行结束时直接打印一次。如果你手动指定了管理员密码，也建议确认一下是否输入正确。

### 3. 检查云防火墙或安全组

至少确认这些端口：

- `18080/tcp`
- `80/tcp`
- 你实际计划使用的 `Socks5 C` 端口，例如 `10808/tcp`

### 4. 进入 UI 录入资源

最小可用流程：

1. 录入 `Clash 订阅 A`
2. 录入 `上游 Socks5 B`
3. 刷新订阅
4. 启动默认路由
5. 复制导出的 `socks5://` 链接

## 可选环境变量

可以在执行 bootstrap 时覆盖默认值：

```bash
echo "[1/2] Downloading bootstrap script from GitHub..." && curl -fL --retry 3 --connect-timeout 15 --max-time 300 https://raw.githubusercontent.com/T-Chen-CN/Clash-Socks-Server-UI/main/bootstrap_ubuntu.sh -o /tmp/clash-socks-bootstrap.sh && echo "[2/2] Starting installer..." && sudo env \
  CSG_PUBLIC_HOST=1.2.3.4 \
  CSG_PUBLIC_PORT=18080 \
  CSG_ADMIN_USERNAME=admin \
  CSG_DEFAULT_ALLOWED_C_PORTS=10808-10999 \
  bash /tmp/clash-socks-bootstrap.sh; \
rm -f /tmp/clash-socks-bootstrap.sh
```

常见变量说明：

- `CSG_PUBLIC_HOST`
  覆盖自动探测出的公网地址，用于默认导出链接。

- `CSG_PUBLIC_PORT`
  WebUI 对外端口，默认 `18080`。

- `CSG_ENABLE_PORT_80`
  是否让 `nginx` 同时监听 `80`，默认 `1`。

- `CSG_ADMIN_USERNAME`
  初始管理员用户名。

- `CSG_ADMIN_PASSWORD`
  初始管理员密码。不传时自动生成。

- `CSG_DEFAULT_ALLOWED_C_PORTS`
  默认允许分配的 C 端口池。

- `CSG_BASE_URL_OVERRIDE`
  覆盖默认 `CSG_BASE_URL`。

- `CSG_PIP_INDEX_URL`
  可选，自定义 pip 源地址。服务器访问 PyPI 较慢时，可以在这里指定你自己的镜像源。

- `CSG_PIP_TIMEOUT`
  pip 单次网络超时时间，默认 `120` 秒。

- `CSG_PIP_RETRIES`
  pip 下载重试次数，默认 `5`。

- `REPO_REF`
  指定 bootstrap 下载哪个分支或 tag。

## 手动源码安装

如果你已经把仓库源码上传到了服务器，可以在仓库目录执行：

```bash
sudo bash install_ubuntu.sh
```

这会复用和 bootstrap 相同的核心安装逻辑。

## 升级建议

如果你将来更新到新版本，建议流程是：

1. 先备份 `data/` 和 `.env`
2. 拉取新版本源码
3. 重新执行安装脚本
4. 检查服务状态和导出是否正常

如果你是用 bootstrap 部署的，通常也可以再次运行 bootstrap 完成升级，但仍然建议先备份。

## 验证部署是否正常

### 服务状态

```bash
sudo systemctl status clash-socks-webui --no-pager -l
sudo systemctl status nginx --no-pager -l
```

### 端口监听

```bash
sudo ss -lntp | grep -E ':(80|18080|18081)\b'
```

### 本机 HTTP 检查

```bash
curl -I http://127.0.0.1:18080/login
curl -I http://127.0.0.1:18081/login
```

如果 `/login` 对 `HEAD` 返回 `405 Method Not Allowed`，通常是正常现象，说明路由存在但该方法不允许。

## 部署模式说明

### 无域名

默认推荐：

- `HTTP + nginx 反代`
- 浏览器可访问
- 不提供受信任证书

### 有域名

如果你需要浏览器原生信任的 HTTPS，需要另外：

- 绑定域名
- 给 `nginx` 或 `caddy` 配证书

这个仓库当前不强制帮你完成证书申请，因为没有域名时也应当能先跑起来。

## 最后提醒

安装脚本能处理服务器内的配置，但不能替你修改云平台控制台里的安全组、SLB、WAF 或其他外部网络策略。部署成功不等于公网一定可达，最终还要看你的云侧设置。
