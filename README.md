# AstrBot Pid2Pdf 插件

一个根据Pixiv ID下载图片并转换为PDF发送的AstrBot插件，可以有效防止R18图片被企鹅的大手拦截。同时具备直接发送图片，查看排行榜，按作者下载，等功能。

## ✅ 已实现功能
- [x] 配置refresh_token 登录 Pixiv API
- [x] `/pid2pdf <PID>` 下载图片并打包为PDF文件发送
- [x] `/pid <PID>` 图片直传模式
- [x] `/pixiv_ranking [类型] [数量]` 获取Pixiv排行榜作品并发送
- [x] `/puid <UID> [数量]` 根据画师UID下载最新作品
- [x] R18内容过滤配置
- [x] AI生成作品过滤配置
- [x] 下载排行榜作品
- [x] 下载指定作者作品
- [x] 简化版指令
- [x] 配置代理
- [x] 使用国内直连反代下载图片

## 🚧 计划功能
- [ ] 按策略清理临时文件
- [ ] 丰富回复信息
- [ ] 搜索功能
- [ ] 监听Pixiv或其他镜像站的链接分享
- [ ] 指定 tag 过滤
- [ ] 订阅功能

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

2. **安装依赖包**
```bash
cd astrbot_plugin_pid2pdf
pip install -r requirements.txt
```

3. **配置参数**
   - 获取Pixiv refresh_token
   - 在插件配置中设置token信息
   - 配置可正常访问pixiv网站的代理

4. **重启AstrBot**
```bash
# 重启AstrBot服务
```

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

# 查看帮助信息
/pid_help

# 简易命令 直接单独发送即可触发
今日色图      #获取 day_r18 排行榜
今日排行榜    #获取 day_male 排行榜
今日ai色图    #获取 day_r18_ai 排行榜
今日ai图    #获取 day_ai 排行榜

```

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
- `week_r18` - R18周榜
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

施工中

## 📂 文件结构

### 核心文件

- `main.py` - 插件入口点和命令注册
- `_conf_schema.json` - 配置模式定义（用于 AstrBot 管理面板显示）
- `requirements.txt` - 依赖库列表

### 数据目录

位于 `AstrBot/data/plugin_data/pid2pdf/`:

- `temp/` - 下载的临时图片目录
- `persistent/` - 生成的 PDF 文件目录

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