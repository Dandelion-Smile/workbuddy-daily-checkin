# WorkBuddy 每日签到与积分领取

适用于 Windows 的本地自动化脚本：每天上午 10 点打开 WorkBuddy，进入账号菜单里的「Buddy 加油站」，检查并领取当天积分。可选 QQ 邮箱通知，确认当天已领取后发送邮件。

## 功能

- 使用 Windows 计划任务每天 10:00 执行，按电脑本地时区计时。
- 当天 10 点之后登录或解锁时补执行，成功后当天不重复打扰。
- 通过 Windows UI Automation 控件名称定位，不依赖固定屏幕坐标。
- 优先复用正在运行的窗口；已有进程却找不到窗口时停止，不重复启动。
- 白屏、数据修复或界面尚未就绪时等待后停止，不强制重启应用。
- 检测「今日已领」并跳过重复领取；无法确认目标时停止并记录结果。
- 失败后每隔 10 分钟重试，最多 3 次；后续解锁仍可再次检查。
- 可选 QQ 邮箱通知，邮件失败后保留领取成功记录，后续只补发通知。
- SMTP 授权码保存在当前 Windows 用户的凭据管理器中。

## 环境要求

- Windows 10 / 11，已安装 Python；当前验证环境为 Python 3.13。
- 已安装 WorkBuddy，并保持登录。
- 电脑开机、唤醒、联网，Windows 已登录并解锁。
- 安装依赖时需要联网；日常运行不需要 Codex 或其他 AI 客户端持续运行。

关机、休眠、停留在登录界面时无法操作 WorkBuddy。脚本不会主动唤醒电脑；当天上午 10 点之后登录或解锁可触发补执行。运行时可能短暂将 WorkBuddy 切到前台。

## 快速开始

1. 下载本仓库，解压到准备长期保留的目录。
2. 将 `config.example.json` 复制为 `config.json`。
3. 编辑 `config.json`，把 `account_menu_name` 填为 WorkBuddy 左下角显示的账号昵称。如安装位置不同，修改 `workbuddy_exe`。
4. 双击 `install.cmd`，安装依赖、检查配置并创建计划任务。
5. 可双击 `run-now.cmd` 手动检查一次。手动执行不受上午 10 点限制。

计划任务名称为 `WorkBuddy-Daily-CheckIn-1000`。以当前用户的普通权限执行，不需要保存 Windows 登录密码。

如需移除计划，在 PowerShell 中运行：

```powershell
.\remove-task.ps1
```

移除任务会保留脚本、日志和本机邮件凭据。

## 配置

| 字段 | 用途 |
| --- | --- |
| `workbuddy_exe` | WorkBuddy 可执行文件路径，支持 `%LOCALAPPDATA%` |
| `account_menu_name` | WorkBuddy 账号菜单的显示昵称，需要自行填写 |
| `claim_button_labels` | 允许点击的领取按钮文字 |
| `runtime_directory` | 日志与每日状态文件的位置 |
| `email_notification.enabled` | 邮件通知开关，默认关闭 |
| `email_notification.sender` | QQ 发件邮箱，默认留空 |
| `email_notification.recipient` | 收件邮箱，默认留空 |

默认运行环境位于 `%LOCALAPPDATA%\WorkBuddyDailyAutomation\runtime`，实际 Python 路径写在本机的 `runtime-path.txt` 中。请保留脚本和运行环境。移动脚本后重新运行安装器更新任务路径。

## 开启邮件通知

1. 在 `config.json` 中填入 `email_notification.sender` 和 `email_notification.recipient`；可以使用同一个 QQ 邮箱收发。
2. 登录 QQ 邮箱网页版，在「设置 → 账号与安全」中按页面提示开启 SMTP 服务并获取授权码，参见 [QQ 邮箱官方说明](https://help.mail.qq.com/detail/0/1087)。
3. 双击 `setup-email.cmd`，在本机窗口输入 16 位邮箱授权码。输入时不会显示字符，请使用授权码，不要使用 QQ 登录密码。
4. 配置工具会验证 SMTP 登录，然后保存凭据并启用通知。可双击 `test-email.cmd` 发送标明「测试」的邮件。

正式通知主题为「WorkBuddy 积分领取通知」，正文为：

> 今日的workbuddyy积分已经领取

无论由脚本领取还是检查时发现已经手动领取，都可以发送当天确认邮件。正常情况下，同一个账号、收件地址每天发送一封。测试邮件不会占用当天的正式通知记录。

使用 `smtp.qq.com:465`，验证 TLS 服务器证书。授权码不写入配置文件或日志。邮件服务器接受邮件后会记录成功，但首次使用仍应检查收件箱和垃圾邮件。

## 日志与执行结果

默认目录：`%LOCALAPPDATA%\WorkBuddyDailyAutomation`。

| 文件 | 说明 |
| --- | --- |
| `checkin.log` | 执行日志；`claimed` 表示确认领取成功，`already_claimed` 表示已领 |
| `last-success.json` | 当天领取确认结果 |
| `mail-success.json` | 当天通知提交记录 |
| `bootstrap-error.log` | 配置或依赖加载失败的记录 |

脚本返回码：`0` 表示成功、已领取或本次无需执行；`75` 表示失败，可根据日志排查。

## 验证与限制

目前已核对 WorkBuddy v5.1.6 中文界面的账号菜单及「今日已领」状态，并验证依赖安装、任务注册和邮件服务器的 TLS 连接。

2026 年 11 月 5 日已通过真实脚本运行及 Windows 计划任务入口验证：程序已运行且积分已领时，复用现有窗口并返回 `already_claimed`，进程退出码与任务结果均为 `0`，WorkBuddy 保持正常响应。

尚未实测「未领取 → 点击 → 服务端确认到账」和「程序未运行时首次启动」的完整分支，也未使用真实邮箱授权码验证邮件投递。首次部署请自行确认一次结果。WorkBuddy 界面、活动或按钮文字变化后，可能需要更新配置或定位逻辑。

包含 14 项模拟测试，覆盖重复启动防护、最小化窗口恢复、白屏停止、邮件每天去重、失败重试、领取结果持久化、TLS 设置和错误信息脱敏。测试不操作 WorkBuddy，也不发送真实邮件。在 Windows 上安装依赖后运行：

```powershell
python -m unittest -v test_notifications.py test_launch_safety.py
```

## 公开仓库中的个人信息处理

仓库只提供空白配置示例，发件邮箱、收件邮箱和账号昵称均需在本机填写。`.gitignore` 排除 `config.json`、运行路径、日志、每日状态文件和虚拟环境。请勿将授权码、密码或其他本机凭据提交到 Git。
