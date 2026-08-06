# ClockIn 小二端帮助中心手动上传指南

目标站点：`yushi1.pages.dev`  
部署包：`outputs/clockin-deploy 5/`

## 一、准备工作

1. 确认部署包已存在：
   - `outputs/clockin-deploy 5/index.html`
   - `outputs/clockin-deploy 5/_headers`
   - `outputs/clockin-deploy 5/version.txt`
2. 部署包中的 `_headers` 已配置 `index.html` 不缓存，上传后刷新即可看到最新内容。

## 二、进入 Cloudflare Pages 项目

1. 打开 [Cloudflare Dashboard](https://dash.cloudflare.com/) 并登录。
2. 在左侧菜单点击 **计算** → **Workers 和 Pages**。
3. 在 Pages 项目列表中找到并点击 **yushi1**。

## 三、上传新部署

1. 在项目页面顶部或右侧，点击 **创建新部署**（或 **上传资产** / **Direct Upload**）。
2. 选择 **上传文件夹**（Upload folder）。
3. 在弹出的文件选择器中，定位到：
   ```
   /Users/lixiaotian/.qoderwork/workspace/mrssl6h69qlreqcf/outputs/clockin-deploy 5
   ```
4. 确认上传文件列表中包含：
   - `index.html`
   - `_headers`
   - `version.txt`
5. 点击 **部署**（Deploy）。

## 四、等待部署完成

1. Cloudflare 会显示部署进度，通常几十秒完成。
2. 部署成功后，会生成一个新的访问地址，例如：
   ```
   https://yushi1.pages.dev
   ```
3. 如果之前打开过该页面，建议强制刷新（Windows: `Ctrl + F5`，macOS: `Cmd + Shift + R`）。

## 五、验证小二端帮助中心

1. 打开 `https://yushi1.pages.dev`。
2. 选择一个员工姓名登录。
3. 点击底部 **帮助** 标签。
4. 在搜索框输入：`每天最多选几个班`，确认出现相关问题并点击展开答案。
5. 输入无意义关键词如 `abcdef`，确认出现「未找到相关问题」并点击 **提交问题反馈**。
6. 到 Supabase Table Editor → `faq_feedback` 表中确认新增一条 `source = 'help-center'` 的记录。

## 六、钉钉机器人（暂不部署）

由于当前组织中「Outgoing 机制」处于维护状态，钉钉群聊机器人部分先跳过。等 Outgoing 机制恢复后再按部署指南的「三、四、六」节补充 Edge Function 与机器人配置。
