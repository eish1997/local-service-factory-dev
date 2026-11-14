# 构建与验收

## Windows 构建入口

以下变量是示例，执行时使用当前版本和新的绝对路径。构建主机 Python 至少 3.11，目标运行时由 `distribution/python-runtime.json` 固定；Node 至少 22。系统 Node 18 曾因构建依赖 ESM 不兼容失败。检查实际版本后选择可用解释器/Node，不为此改全局 PATH。

```powershell
$runtimeSpec = Get-Content distribution/python-runtime.json -Raw | ConvertFrom-Json
py -3.11 -m tools.stage_distribution --confirm-build --python-zip <已校验的官方ZIP> --python-sha256 $runtimeSpec.sha256 --destination <新暂存目录>
$env:FACTORY_DISTRIBUTION_STAGE = '<新暂存目录>'
$env:FACTORY_DISTRIBUTION_OUTPUT = '<新产物目录>'
node dashboard/tools/build-installer.js --confirm-build
```

离线 wheelhouse 可在本次进程设置 `PIP_NO_INDEX=1`、`PIP_FIND_LINKS=<目录>`，由锁文件和哈希约束安装；未齐全时明确失败，不静默换版本。构建工具已复用已安装的 Electron，避免重复下载。若复用旧版私有 Python，先核对运行时规格和依赖锁未改变，在新 stage 中调用维护代码 `stage_engine` 生成新引擎，再复制已校验 runtime；运行相同独立检查。不要复用旧引擎或已冻结用户规则目录。

## 构建内容

- 安装程序 `LocalServiceFactory-<版本>-setup.exe`、同名 `.blockmap`、`latest.yml` 必须版本一致。签名清单由现有发布协议生成。
- 独立 Python 的 `_pth`、二进制依赖及引擎可离线启动；基础规则通过脱敏白名单导出，`maintainer_mode=false`。
- `.env`、签名私钥、任务/图片/客户历史不进入资源树；只检查已知资源目录，不能递归打印整个生产目录。
- Ed25519 更新签名和 Windows Authenticode 是两件事；没有证书不能报告发布者身份签名成功，也不要把构建日志中的 signing 行当成证书证据。

## 验收强度

使用本版隔离测试目录和 `FACTORY_DATA_HOME`，不得连到真实客户 workspace 或启动付费 API。

1. 短模块按改动串行运行：`dashboard/tests/updates.test.js`、`installed-bootstrap.test.js`、`tests/test_update_transport.py`；引擎独立运行验证现有八个业务的组装。bootstrap 测试用 `FACTORY_TEST_DISTRIBUTION_STAGE` 指定本版 stage。不运行全量 safety 模块或任何 dry-run。
2. 新运行时/安装逻辑用实际 NSIS 安装到隔离目录，等安装进程结束后再检查依赖、启动和业务入口，不能在复制未完成时判断缺依赖。
   优先用独立 Windows 用户或虚拟机。已有同 appId 的机器级/用户级安装时，仅 /D 不构成隔离，NSIS 仍可能卸载或迁移原安装；先核对 HKLM/HKCU 安装范围，测试明确指定 /currentuser。安装器自动重启不保证继承隔离环境变量，验证时禁止自动重启，再用明确测试环境手动启动。不得把这种限定范围的验证声称为全部安装模式无人值守验收。
3. 更新模块变化时，使用安装包内 `resources/app.asar/update-service.js`、真实 electron-updater 与 NSIS，核验摘要和备份，验证后台任务阻止安装、无任务退出触发安装、启动后 `install-result.json` 的 expected/actual 相同且安装标志清理。
4. Electron 的普通 fs 会虚拟展开 ASAR。程序备份须用 `original-fs`，临时目录完整复制后原子改名；核对备份 ASAR 原始字节。失败的临时目录不代表有效备份，不能据其存在跳过备份。
5. 为省时，可把已经从公开 URL 下载并完整核验的安装包放到官方 updater 缓存，再核验 `latest.yml` 的 SHA512。结果必须记明缓存复用。低版本测试适配器只能证明更新模块与安装链路，不能证明真实旧版程序具备相同逻辑或全新 Windows 兼容。

2026-09-30 的历史验证：1.3.1 修复 ASAR 备份，并通过安装包模块/低版本适配器/真实 NSIS 验收。1.3.0 的备份逻辑有缺陷，首次安装应从修复版开始；不要以历史测试断言 1.3.0 能自动升级。全新 Windows 虚拟机和付费生图未验收。
