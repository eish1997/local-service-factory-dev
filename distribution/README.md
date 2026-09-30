# 软件与规则发布（1.3.1）

维护者：`eish1997`。软件仓库 `local-service-factory-releases`，规则仓库 `local-service-factory-rules`，均公开。2026-09-30 已正式发布软件 1.3.1 和规则 1790730656981293500，公开下载、文件摘要和发布签名均已验证。软件 Release：http<local-path>

## 日常约定

Agent 修改规则后先本地检查，不自动上传。收到“发布项目更新”才执行 rules publish；收到“构建安装包”才准备正式构建资源并运行 NSIS；收到“发布软件更新”才上传软件。使用端不持有发布凭证，界面没有发布接口。

Agent 与看板共用 `python factory.py rules/updates`。命令均从标准输入接收 JSON，并返回统一 JSON。示例中的版本号采用递增正整数字符串；省略版本由本地生成。不要将密钥粘贴到对话或写入命令历史。

## 首次发布准备

1. 在维护电脑用 `gh auth login` 登录，或在该进程的私有环境设置 `GH_TOKEN`。工具只在内存读取凭证，不打印、不打包。
2. 明确要求初始化后，调用 `updates setup`，输入 `{"authorization":"initialize_update_repositories"}`。只创建缺少的公开仓库并初始化默认分支，不发布版本，也不改变已有私有仓库的可见性。
3. 发布签名使用 Ed25519。本机私钥位于 `.runtime/private/release-signing.pem`，公钥已写入 `update-config.json`。应另行妥善备份私钥；私钥不进入安装包、规则包或公开仓库。可通过 `FACTORY_RELEASE_KEY_FILE` 和 `FACTORY_RELEASE_KEY_ID` 指定维护端签名密钥。公钥轮换需先发含新旧公钥的软件版本，再改用新私钥签名。

## 项目规则发布

- `rules release-plan` 输入 `{}`：导出白名单数据、排除私密字段，验证八个业务的本地组装，保存不可覆盖的新版本计划并返回差异清单。
- `rules publish` 输入 `{"version":"计划返回的版本","authorization":"publish_project_update"}`：签名、上传完整规则 ZIP 和清单，确认公开 ZIP 可下载后，用 GitHub Contents SHA 比较并交换最新版本指向。
- `rules sync` 输入 `{}`：使用端校验并激活；维护端只读取远端版本和基准 SHA，不覆盖编辑文件。并发发布冲突后，先 sync 再重新 release-plan。
- `rules rollback` 输入 `{"from_version":"本机保存的历史发布计划版本","authorization":"publish_project_update"}`：复用历史数据，重新验证后以更高版本发布，绝不倒退版本号。旧计划保留在 `.runtime/updates/release_plans/`。
- `updates status/check` 输入 `{}`：查询状态或请求检查。软件下载安装由桌面进程执行，Agent 的检查请求通过本地记录交给同一个服务；看板未打开时等待下次启动。

白名单固定在 `rules-fields.json`，当前共 36 个数据文件。`configs/prompt_templates.json` 是实际组装读取的额外模板段落，默认空列表，不改变既有提示词；支持 shared 或按业务的 cover/detail 段落，只允许 `{phone}`、`{category}`、`{services}` 占位，不执行代码。已有 Python 中的提示词算法通过软件更新发布；`prompt_template_storefront.md` 是参考说明，不将整篇说明直接附加到图片提示词。

客户端下载后逐文件验证，检查路径、大小、私密字段、业务结构和软件兼容性。整包通过后只原子切换版本指针。每次组装固定一个版本，批次 snapshot 记录版本；后台 worker 恢复该批次原规则目录，缺失则明确停止，不能改用最新规则。规则历史不自动清理。

## 正式 Windows 构建与软件发布

必须先有明确的构建指令。本轮用户明确要求补齐所有未完成工作，已完成正式独立运行构建、NSIS 安装和 GitHub 发布；旧安装包保留。

1. 官方 Python 3.11.9 x64 嵌入 ZIP 的地址和 SHA256 固定在 `python-runtime.json`。依赖使用 `requirements-runtime.lock` 的 Windows CPython 3.11 轮包哈希。
2. 使用 Python 3.11 或更高版本，在工厂根目录调用 `python -m tools.stage_distribution --confirm-build --python-zip <ZIP绝对路径> --python-sha256 <已固定摘要> --destination <全新暂存目录>`。该步骤准备干净引擎、36 个基础规则文件、Python 和依赖，并使用内置解释器检查八个业务。不会复制 `.env`、任务、原图、私钥或客户历史。
3. 设置本地构建环境的 `FACTORY_DISTRIBUTION_STAGE` 为该暂存目录，使用 Node.js 22 或更高版本，在 dashboard 执行 `npm run build:installer -- --confirm-build`；可设置 `FACTORY_DISTRIBUTION_OUTPUT` 为新的产物目录，保留旧安装包。构建目标 NSIS x64，`--publish never`，不会顺便发布。
4. 如需 Windows 发布者身份签名，通过 electron-builder 标准 `CSC_LINK` / `CSC_KEY_PASSWORD` 配置 Authenticode 证书；证书和密码不进仓库。应用自己的发布签名校验始终启用，不能代替 Windows 的发布者身份签名。
5. 明确要求发布后，调用 `updates release-plan`，输入 `{"directory":"构建产物目录"}`；再调用 `updates publish`，输入相同 directory、计划返回的 files，以及 `authorization:"publish_software_update"`。

软件发布先取得 GitHub 原子发布锁，上传安装程序、blockmap、latest.yml、签名清单到草稿版本，公开为非最新版本；验证公开下载内容及签名后才设为最新。若中途失败，保留版本文件和 `software-publish-lock` 标签；Agent 检查是否仍有发布进程、核对内容后，才可处理锁并重新发布，不能无条件抢锁。

## 使用端目录与恢复

安装目录包含程序、生成引擎和私有 Python；用户目录为 Electron userData 下的 workspace，保存 `.env`、任务、冻结批次、规则版本与状态。图片仍遵循用户选择的资产目录。首次启动从软件内置的基础规则建立版本 1，离线即可使用。

软件启动检查，此后每六小时检查，验证下载包签名及摘要后备份当前安装目录。正常退出时再次取得任务管理锁、确认没有后台任务，再写安装标志并启动安装；安装标志存在时 Agent 和看板都不能启动/续接生产。启动已验证的程序后清理标志并记录实际安装版本。

规则更新失败保留活动版本；软件下载/验证/备份失败不执行安装。旧程序备份在用户目录 `.runtime/updates/previous-app/<旧版本>/`，验证过的安装包在 `.runtime/updates/installers/`。NSIS 实际安装失败时，可从旧程序备份启动恢复；不要删除用户 workspace 或资产目录。本版没有修改用户数据格式，无需批次迁移。后续需要迁移时必须先增加专门备份与兼容测试。

源码维护端不下载/安装软件更新，规则同步只检查远端，不覆盖编辑区。使用端隐藏/删除项目记录独立存放，规则刷新不会重新显示已隐藏项目。

## 本次验证边界

已通过更新传输回归、规则更新回归、Electron 更新服务和独立启动测试。已实际发布两个 GitHub Release，验证无凭证公开下载、摘要与签名，并在隔离使用端完成规则同步。实际 NSIS 安装的软件可独立启动，其内置 Python 及全部八个业务组装通过。自动升级验收采用较低版本测试适配器驱动真实 electron-updater 和 NSIS；公开下载验证后的安装包复用官方更新缓存，避免重复网络下载。全新 Windows 虚拟机和真实付费生图未执行。当前无 Windows Authenticode 发布者证书，应用的 Ed25519 发布签名校验已启用。
