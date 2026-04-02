# Security Policy

## Supported Versions

当前仓库默认只维护主分支上的最新版本。

## Reporting a Vulnerability

如果你发现了以下问题，请不要先公开发布细节：

- WebUI 认证绕过
- Session / Cookie 安全问题
- 任意文件读取 / 命令执行
- 未授权代理开放
- 明文泄露账号、密码、密钥

请通过 GitHub 私信、私有渠道或仓库所有者指定的联系方式反馈，并尽量附带：

- 影响范围
- 复现步骤
- 预期结果与实际结果
- 是否需要特定配置才能触发

## Operational Security Notes

- 不要把 `.env`、`data/`、`runtime/`、`logs/` 上传到公开仓库
- WebUI 建议只通过 HTTPS 对外提供
- Socks5 端口建议使用随机高位端口并配合云防火墙限源
- 所有默认或示例密码在生产环境都必须立即替换
