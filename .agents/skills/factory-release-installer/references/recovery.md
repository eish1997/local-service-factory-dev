# 恢复同一次软件发布

只在已授权发布因网络/进程中断时读取。先确定失败阶段；不要沿用 `.runtime/private` 里带固定版本、Release ID 的一次性脚本。

## 身份与网络

`gh` 当前可位于 `<local-path>`；应用旧 PATH 时仅把该目录加到本次进程 PATH。`gh auth status` 可展示账号和授权范围，不运行会输出 token 的命令到聊天。

既有 Windows 系统代理可用 `urllib.request.getproxies()` 读取。Python urllib 会使用它，Go gh 通常需本次进程 `HTTPS_PROXY`；`GODEBUG=http2client=0` 是遇到 HTTP/2 断连时的可选诊断，不能当成永久最佳配置。不要改系统代理或引入新的中转。此次 CLI 大文件失败后，使用既有代理的 curl 上传成功；直连上传没有持续收益。

## 状态检查与继续

1. 核对本地保存的版本计划、所有产物摘要、正在运行的发布进程；读取配置仓库的 `software-publish-lock`、精确 `v<版本>` Release 和 assets。
2. 若还在上传，只观察该进程。无进程时逐项核对 assets 的名称、状态、大小和 GitHub digest；不确定是否成功的 POST/上传必须先做这一步。有效资源不重传；缺失资源才上传。冲突、同名不同摘要、其他人的锁或最新版已更高时停止，保留证据，不删除/覆盖资源。
3. 只能恢复本次计划对应的草稿。可使用 `gh release upload`，不使用 `--clobber`。CLI 连续失败时可用 curl 上传到 GET Release 返回的官方 `http<local-path>` URL：token 由 keyring 在内存读取，经 curl `--config -` 的 stdin 传头；不写 token 临时文件、不放命令行、不输出 verbose 请求、不跟随携带凭证的重定向。上传限时最多五分钟，失败先检查远端；最多尝试两种有证据可用的传输方法，仍失败则停止本轮。
4. 四项资源齐全且摘要一致后公开该 Release，先设置 `make_latest:false`。用本 skill 的 `verify_public_release.py` 完成真实公开下载和签名校验；允许复用已核验文件和续传分片，最多六并发，每片两次有限尝试。
5. 校验后才设置该版本为 latest。GitHub 即使接收非最新发布，也需实际读取 `/releases/latest` 核对指向；不能仅依据 PATCH 意图作判断。
6. 最后读取并核对本次锁仍是已记录的同一 ref/object SHA，确认没有其他发布进程，才释放本次 `software-publish-lock`；变化或归属不明时停止。锁 DELETE 超时也先 GET，不能直接重复删除。

## 完成证据

记录 release URL、资产摘要、下载目录、签名核验结果、实际 latest tag 和锁状态。保存进度供下一轮恢复。README 写已完成的分发状态，不能把仍是草稿或仅上传成功写成可自动更新。
