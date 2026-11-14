# 在另一台电脑开发

开发仓库 `eish1997/local-service-factory-dev` 是私有源码仓库。软件安装包、云端规则仍在各自的公开分发仓库。提交开发源码不会自动构建、发布或生图。

## 首次克隆

安装 Git、Python 3.11 或更新版本、Node.js 22 或更新版本，并在本机登录拥有私有仓库权限的 GitHub 账号。

```powershell
gh auth login
gh repo clone eish1997/local-service-factory-dev
cd local-service-factory-dev
py -3.11 -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements.txt
npm --prefix dashboard ci
$env:ROAD_RESCUE_PYTHON = (Resolve-Path .venv/Scripts/python.exe).Path
npm --prefix dashboard start
```

Agent 打开整个仓库并先读 AGENTS.md。项目 skill 位于 `.agents/skills/`，不依赖原电脑的个人 skill 目录。Agent 与看板使用同一解释器和公共命令；命令示例中的 python 可换成本机 `.venv/Scripts/python.exe`。

生产前通过本机 `.env`/看板密码表单配置密钥及已有可信渠道，明确本批次的组数、号码与范围。仓库不保存原电脑的客户资料、生成图片、任务许可、签名私钥或账号凭证；新电脑不能据此继续原电脑尚未同步的生产任务。

## 日常开发

```powershell
git pull --ff-only
# 修改代码，按 Agent 指引做相关检查
git status --short
git add <本次修改的源码或规则文件>
git commit -m "Describe the change"
git push
```

多台电脑先拉取后开发。有未提交变更时先检查并保留自己的修改，不用强推或硬重置覆盖另一台电脑。API密钥、客户记录、运行状态、node_modules与构建产物由.gitignore排除；提交前仍检查暂存内容，不新增秘密到受跟踪文件。

发布新版安装包使用 factory-release-installer；发布项目规则使用 factory-release-rules。发布需要本机 gh 登录及既有 Ed25519 发布私钥，私钥须通过用户自己的可信离线方式配置，不通过 Git 传输，也不能重新生成密钥冒充原公钥。

## 原生产工作区首次导出

`python development/export_source.py --destination <全新目录>` 只生成干净开发源码，复用规则白名单及脱敏逻辑，不上传、不复制运行数据、不覆盖已有 Git 工作副本。首次导出后在该副本初始化 Git 并推送。以后在克隆/开发副本中直接使用标准 Git 流程。

如果仍在原生产工作区修改，源码不会自动同步到开发副本；再次导出到新目录后审阅差异，再合并到 Git 副本。不要整目录覆盖已存在的开发副本或生产用户数据。

## 使用 skill 整理推送

开发任务完成后，在对话中调用：`使用 $factory-push-source，把已完成的开发源码和 Agent 指引整理并推送到私有开发仓库。`

该 skill 位于 `.agents/skills/factory-push-source/`，会判断当前是 Git 开发副本还是原生产目录，检查并合并远端改动，脱敏审阅、提交推送并验证远端提交。另一个对话仍在修改时等待开发完成；仅创建或查看 skill 不会触发推送。它与安装包发布、云端规则发布相互独立。
