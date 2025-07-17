# AstrBot Pid2Pdf 插件

一个用于AstrBot的插件，可以根据Pixiv ID下载图片并合并为PDF文件发送给用户。

## 📋 功能特性

### ✅ 已实现功能
- [x] 监听指令 `/pid2pdf <PID>` - 根据Pixiv ID下载图片并生成PDF
- [x] 使用refresh_token登录Pixiv API
- [x] 下载图片到本地临时目录
- [x] 将图片打包为PDF文件
- [x] 本地临时存储（图片，PDF）
- [x] 自动清理临时文件
- [x] 帮助指令 `/pid_help` - 显示使用说明

### 🚧 计划功能
- [ ] 配置页面（token，代理，频率限制，追加功能）
- [ ] 图片直传模式
- [ ] R18 tag 筛选
- [ ] 按作者下载
- [ ] 排行榜下载

## 🚀 快速开始

### 环境要求
- Python 3.7+
- AstrBot 框架
- 有效的Pixiv账号

### 安装步骤

1. **克隆插件到AstrBot插件目录**
```bash
cd /path/to/astrbot/plugins
git clone https://github.com/yourusername/astrbot_plugin_pid2pdf.git
```

2. **安装依赖包**
```bash
cd astrbot_plugin_pid2pdf
pip install -r requirements.txt
```

3. **配置Pixiv账号**
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

1. **下载单图作品**
```
用户: /pid2pdf 987654321
机器人: 开始处理Pixiv ID: 987654321，请稍候...
机器人: PDF生成完成: pixiv_987654321.pdf
```

2. **下载多图作品**
```
用户: /pid2pdf 123456789
机器人: 开始处理Pixiv ID: 123456789，请稍候...
机器人: 下载了 5 张图片
机器人: PDF生成完成: pixiv_123456789.pdf
```

## ⚙️ 配置说明

### Pixiv API配置

插件需要配置Pixiv API的认证信息：

```python
# 在main.py中配置
self.api.auth(refresh_token="your_refresh_token")
```

### 代理设置（可选）

如果需要使用代理访问Pixiv：

```python
# 配置代理
self.api.set_proxy("http://127.0.0.1:7890")
```

## 📦 依赖包

- `pixivpy3>=3.7.0` - Pixiv API客户端
- `Pillow>=9.0.0` - 图片处理
- `reportlab>=3.6.0` - PDF生成
- `requests>=2.28.0` - HTTP请求
- `aiohttp>=3.8.0` - 异步支持

## 🔧 开发说明

### 项目结构
```
astrbot_plugin_pid2pdf/
├── main.py              # 主插件文件
├── requirements.txt      # 依赖包列表
├── metadata.yaml        # 插件元数据
├── README.md           # 项目说明
└── LICENSE             # 开源协议
```

### 核心功能模块

1. **Pixiv API集成** - 使用pixivpy3库访问Pixiv API
2. **图片下载** - 支持单图和多图作品下载
3. **PDF生成** - 使用reportlab将图片合并为PDF
4. **文件管理** - 临时文件创建和清理
5. **错误处理** - 完善的异常处理机制

### 扩展开发

如需添加新功能，可以参考以下结构：

```python
@filter.command("new_feature")
async def new_feature(self, event: AstrMessageEvent):
    """新功能实现"""
    # 实现逻辑
    pass
```

## 🐛 故障排除

### 常见问题

1. **Pixiv API认证失败**
   - 检查refresh_token是否正确
   - 确认账号状态正常

2. **图片下载失败**
   - 检查网络连接
   - 确认PID是否存在
   - 检查代理设置

3. **PDF生成失败**
   - 确认Pillow和reportlab已正确安装
   - 检查磁盘空间是否充足

### 日志查看

插件运行日志会输出到AstrBot的日志系统中，可通过以下方式查看：

```bash
# 查看AstrBot日志
tail -f /path/to/astrbot/logs/astrbot.log
```

## 📄 许可证

本项目采用 [LICENSE](LICENSE) 许可证。

## 🤝 贡献

欢迎提交Issue和Pull Request来改进这个插件！

### 贡献指南

1. Fork 本仓库
2. 创建特性分支 (`git checkout -b feature/AmazingFeature`)
3. 提交更改 (`git commit -m 'Add some AmazingFeature'`)
4. 推送到分支 (`git push origin feature/AmazingFeature`)
5. 开启 Pull Request

## 📞 联系方式

- 作者: Joker42S
- 项目地址: https://github.com/yourusername/astrbot_plugin_pid2pdf
- 问题反馈: https://github.com/yourusername/astrbot_plugin_pid2pdf/issues

---

**注意**: 使用本插件时请遵守Pixiv的服务条款和版权规定。仅用于个人学习和合法用途。