---
name: "remote-connector"
description: "通过SSH连接远程服务器，支持执行命令、上传文件和下载文件。当用户需要对配置的远程服务器进行操作时调用此技能。"
---

# 远程连接器

通过 SSH/SCP 提供远程服务器连接能力，支持执行命令、上传文件和下载文件。

## 配置

连接参数从 `.trae/config.ini` 中读取：

| 字段 | 说明 |
|------|------|
| `server_ip` | 远程服务器 IP 地址 |
| `key_file` | SSH 私钥路径（`~` 会展开为用户主目录） |
| `user` | SSH 登录用户名 |
| `work_dir` | 项目工作目录绝对路径 |

## 使用方法

辅助脚本：`.trae/scripts/remote.ps1`

### 执行远程命令

```powershell
powershell -ExecutionPolicy Bypass -File .trae/scripts/remote.ps1 `
  -Action exec -ConfigFile .trae/config.ini -Command "<命令>"
```

### 上传文件

```powershell
powershell -ExecutionPolicy Bypass -File .trae/scripts/remote.ps1 `
  -Action upload -ConfigFile .trae/config.ini `
  -LocalPath "<本地路径>" -RemotePath "<远程路径>"
```

### 下载文件

```powershell
powershell -ExecutionPolicy Bypass -File .trae/scripts/remote.ps1 `
  -Action download -ConfigFile .trae/config.ini `
  -RemotePath "<远程路径>" -LocalPath "<本地路径>"
```

## 注意事项

- 确保 `.trae/config.ini` 中指定的 SSH 密钥文件存在
- 已设置 `StrictHostKeyChecking=no` 避免首次连接交互提示
- 连接超时 10 秒
- `-Command` 包含特殊字符时用双引号包裹
- `-LocalPath` 和 `-RemotePath` 请使用绝对路径
