# AstrBot Pid2Pdf 插件

一个根据Pixiv ID下载图片并转换为PDF发送的AstrBot插件，可以有效防止R18图片被企鹅的大手拦截。同时具备直接发送图片，查看排行榜，按作者下载，等功能。

## ✅ 已实现功能
- [x] 配置refresh_token 登录 Pixiv API
- [x] `/pid2pdf <PID>` 下载图片并打包为PDF文件发送
- [x] `/pid <PID>` 图片直传模式
- [x] R18内容过滤配置
- [x] AI生成作品过滤配置
- [x] 下载排行榜作品
- [x] 下载指定作者作品
- [x] 简化版指令
- [x] 配置代理
- [x] 使用国内直连反代下载图片
- [x] 订阅功能
- [x] 订阅后立即拉取一次最新作品，并把最新作品 PID 记入订阅记录
- [x] 发送 Pixiv 作品链接自动走 `/pid`
- [x] 发送 Pixiv 画师链接自动走 `/订阅画师`
- [x] 作品信息（标题/作者/标签/R18/AI）在图片或 PDF 之前发出
- [x] 未打包全的 PDF 以 `_preview` 命名，不会污染 `/pid2pdf` 的完整版缓存
- [x] 多图作品按页码顺序发送
- [x] 缓存上限与后台自动清理（优先清理 PDF）


## 🚧 计划功能
- [ ] 搜索功能
- [ ] 指定 tag 过滤
- [ ] 监听 Pixiv 镜像站的链接分享

## 📦 环境要求
- 安装AstrBot
- 有效的Pixiv账号
- Pixiv refresh_token，获取方法可参考：[Pixiv OAuth Flow](https://gist.github.com/ZipFile/c9ebedb224406f4f11845ab700124362) （如果无法直连pixiv，需要配置全局TUN代理）

## 🛠️ 安装步骤

1. **克隆插件到AstrBot插件目录**
```bash
cd /path/to/astrbot/plugins
git clone https://github.com/Joker42S/astrbot_plugin_pid2pdf.git
```

2. **重启AstrBot**
 
3. **配置参数**
   - 获取Pixiv refresh_token
   - 在插件配置中设置token信息
   - 配置可正常访问pixiv网站的代理


## 📖 使用方法

### 基本命令

```bash
# 下载指定PID的图片并生成PDF
/pid2pdf 123456789

# 下载指定PID的图片并直接发送
/pid 123456789

# 获取Pixiv排行榜作品（默认日榜前5个）
/pixiv_ranking

# 获取指定类型排行榜
/pixiv_ranking week 3

# 获取指定数量的排行榜作品
/pixiv_ranking 10

# 根据画师UID获取最新作品（默认5个）
/puid 12345678

# 获取指定数量的画师作品
/puid 12345678 3

# 订阅画师（订阅成功后会立刻拉取一次最新作品并发送）
/订阅画师 12345678

# 取消订阅
/删除订阅 12345678

# 立即刷新一次全部订阅
/刷新订阅

# 立即按上限清理一次缓存
/清理缓存

# 查看当前配置状态（含缓存占用）
/pid_config

# 查看帮助信息
/pid_help

# 简易命令 直接单独发送即可触发
今日色图      #获取 day_r18 排行榜
今日排行榜    #获取 day_male 排行榜
今日ai色图    #获取 day_r18_ai 排行榜
今日ai图    #获取 day_ai 排行榜

# 直接发 Pixiv 链接（群里发即可，无需命令前缀）
https://www.pixiv.net/artworks/147446028   #等同于 /pid 147446028
https://www.pixiv.net/users/54891433       #等同于 /订阅画师 54891433

```

> 链接识别支持 `artworks/`、`i/`、`member_illust.php?illust_id=` 三种作品链接形式，
> 以及 `users/` 画师链接；带语言前缀（`/en/`、`/zh-tw/`）也能识别。
> 目前仅在**群聊**生效（与简易命令一致），私聊暂不触发。
>
> `/pid`、`/pid2pdf`、`/订阅画师` 的参数同样可以直接填链接，例如
> `/pid https://www.pixiv.net/artworks/147446028`；这类指令写法不会被链接识别重复处理。

### 排行榜类型说明

- `day` - 日榜（默认）
- `week` - 周榜
- `month` - 月榜
- `day_male` - 男性向日榜
- `day_female` - 女性向日榜
- `week_original` - 原创周榜
- `week_rookie` - 新人周榜
- `day_manga` - 漫画日榜
- `day_r18` - R18日榜
- `day_male_r18` - R18男性向日榜
- `day_female_r18` - R18女性向日榜
- `week_r18` - R18周榜
- `week_r18g` - R18G周榜
- `day_ai` - AI作品日榜
- `day_r18_ai` - R18 AI日榜
- `week_r18_ai` - R18 AI周榜

### 使用示例

1. **输入pid发送PDF**
```
用户: /pid2pdf 987654321
机器人: 开始获取 Pixiv 作品: 987654321，请稍候...
机器人: pixiv_987654321.pdf
```

2. **输入pid发送图片**
```
用户: /pid 987654321
机器人: PID:987654321 [图片]
```

3. **获取排行榜作品**
```
用户: /pixiv_ranking day 3
机器人: 正在获取Pixiv day 排行榜前 3 个作品，请稍候...
机器人: #1 PID: 123456789
       标题: 美丽的插画
       作者: 画师名
       浏览: 50000 | 收藏: 2000
       [图片预览]
       ---
       #2 PID: 987654321
       ...
```

4. **获取画师最新作品**
```
用户: /puid 12345678 3
机器人: 开始获取画师 12345678 的最新 3 个作品，请稍候...
机器人: 画师: 某某画师 (UID: 12345678)
       共找到 3 个作品
       #1 PID: 111111111
       标题: 最新插画作品
       发布日期: 2024-01-15
       浏览: 30000 | 收藏: 1500
       [图片预览]
       ---
       #2 PID: 222222222
       ...
```

## ⚙️ 配置说明

| 配置项 | 类型 | 默认值 | 说明 |
| --- | --- | --- | --- |
| `refresh_token` | string | 空 | Pixiv refresh_token，必填 |
| `proxy` | string | 空 | 网络代理地址 |
| `use_reverse_proxy` | bool | false | 是否用反代下载图片 |
| `reverse_proxy` | string | 空 | 反代地址 |
| `r18_mode` | string | 过滤 R18 | `过滤 R18` / `允许 R18` / `仅 R18` |
| `ai_filter_mode` | string | 显示 AI 作品 | `显示 AI 作品` / `过滤 AI 作品` / `仅 AI 作品` |
| `easter_egg` | bool | false | 随机彩蛋开关 |
| `enable_subscription` | bool | false | 是否启用订阅 |
| `refresh_interval` | int | 90 | 订阅刷新间隔（分钟） |
| `max_update_limit` | int | 10 | 单次更新最多处理多少个画师 |
| `max_cache_size` | int | 1024 | 缓存上限（**MB**），`0` 表示不限制 |
| `easter_egg_list` | list | 4 项 | 彩蛋可选的排行榜 |

### 缓存清理

`temp/` 里的图片和 `persistent/` 里的 PDF 合计超过 `max_cache_size` 后会后台自动清理：

- **优先删 PDF**。PDF 是由 `temp/` 里的图片打包出来的，删掉之后本地图片还在，
  下次 `/pid2pdf` 只要重新打包即可，不需要重新下载；只有 PDF 全删完仍然超标时，
  才会去删 `temp/` 里的图片目录。
- 两者都按**最旧优先**清理，并且一次清到上限的 90%，避免刚清完又被顶上去反复触发。
- `subscriptions.json`、`egg_trigger_record.txt` 是插件状态而不是缓存，**永远不会被删**。
- 清理跑在后台线程里，不阻塞处理消息；正在下载的作品、刚打包好还没发出去的 PDF
  都会被跳过（10 分钟内碰过的缓存一律不动，等价于 LRU）。
- 想手动腾地方就发 `/清理缓存`，`/pid_config` 可以看到当前占用。

## 📂 文件结构

### 核心文件

- `main.py` - 插件入口点和命令注册
- `_conf_schema.json` - 配置模式定义（用于 AstrBot 管理面板显示）
- `requirements.txt` - 依赖库列表

### 数据目录

位于 `AstrBot/data/plugin_data/pid2pdf/`:

- `temp/<PID>/` - 下载的原始图片缓存（按页码命名 `image_0.jpg`、`image_1.jpg` ...）
- `persistent/` - 生成的 PDF 文件目录
  - `pixiv_<PID>.pdf` - `/pid2pdf` 生成的**完整**作品 PDF，再次请求同一 PID 时直接复用
  - `pixiv_<PID>_preview.pdf` - 订阅 / 排行榜等场景只拿到部分页数时的**预览版** PDF
  - `pixiv_<排行榜模式>_<日期>_preview.pdf` - 排行榜汇总 PDF（每个作品只取第一张）
  - `subscriptions.json` - 订阅记录（插件状态，不参与清理）
  - `egg_trigger_record.txt` - 彩蛋触发时间（插件状态，不参与清理）

> 预览版文件名带 `_preview` 后缀，所以 `/pid2pdf` 的缓存查找（只看 `pixiv_<PID>.pdf`）
> 不会误命中一份只有前 10 张的 PDF。想强制重新生成完整版时，删掉对应的
> `pixiv_<PID>.pdf` 即可。

## 📄 许可证

本项目遵循开源许可证，具体许可证信息请查看项目根目录下的 LICENSE 文件。

## 🙏 特别感谢

本项目基于或参考了以下开源项目:

- [AstrBot](https://github.com/Soulter/AstrBot) - AstrBot平台
- [pixivpy3](https://github.com/upbit/pixivpy) - Pixiv API
- [JM-Cosmos](https://github.com/GEMILUXVII/astrbot_plugin_jm_cosmos) - AstrBot插件，下载JM漫画并转PDF发送
- [PixivSearch](https://github.com/vmoranv/astrbot_plugin_pixiv_search) - AstrBot Pixiv 搜索插件
---

**注意**: 使用本插件时请遵守Pixiv的服务条款和版权规定。仅用于个人学习和合法用途。
