# AstrBot Pid2Pdf 插件

一个用于AstrBot的插件，可以根据Pixiv ID下载图片并合并为PDF文件发送给用户。

## ✅ 已实现功能
- [x] 配置refresh_token 登录 Pixiv API
- [x] `/pid2pdf <PID>` 下载图片并打包为PDF文件发送
- [x] 保留pdf，清理其他临时文件

## 🚧 计划功能
- [ ] 配置代理
- [ ] 图片直传模式
- [ ] 下载指定作者作品
- [ ] 下载排行榜作品
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

4. **重启AstrBot**
```bash
# 重启AstrBot服务
```

## 📖 使用方法

### 基本命令

```bash
# 下载指定PID的图片并生成PDF
/pid2pdf 123456789

# 查看帮助信息
/pid_help
```

### 使用示例

1. **输入pid下载**
```
用户: /pid2pdf 987654321
机器人: 开始获取 Pixiv 作品: 987654321，请稍候...
机器人: pixiv_987654321.pdf
```

2. **已下载过的pid**
```
用户: /pid2pdf 987654321
机器人: pixiv_987654321.pdf
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