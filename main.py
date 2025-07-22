import os
import tempfile
import asyncio
from typing import List
from pathlib import Path

from astrbot.api.event import filter, AstrMessageEvent, MessageEventResult
from astrbot.api.star import Context, Star, register, StarTools
from astrbot.api import logger
from astrbot.api.message_components import *

# 引入所需的第三方库
try:
    from pixivpy3 import ByPassSniApi
    import requests
    import img2pdf
    import io

except ImportError as e:
    logger.error(f"缺少必要的依赖包: {e}")
    logger.error("请安装: pip install pixivpy3 pillow reportlab requests")

@register("pid2pdf", "Joker42S", "根据Pixiv ID下载图片并保存为PDF发送", "1.0.0")
class Pid2PdfPlugin(Star):
    def __init__(self, context: Context, config : dict):
        super().__init__(context)
        self.config = config
        self.papi = None
        self.temp_dir = None
        self.refresh_token = None
        self.proxy = None

    async def initialize(self):
        """插件初始化方法"""
        try:
            # 初始化Pixiv API
            self.papi = ByPassSniApi()
            self.plugin_name = "pid2pdf"
            # 从配置中获取refresh_token和代理设置
            self.refresh_token = self.config.get("refresh_token", "")
            self.proxy = self.config.get("proxy", "")
            # 设置代理（如果配置了）
            
            # 使用refresh_token登录
            if self.refresh_token:
                try:
                    self.papi.auth(refresh_token=self.refresh_token)
                    logger.info("Pixiv API登录成功")
                except Exception as e:
                    logger.error(f"Pixiv API登录失败: {e}")
                    logger.warning("请检查refresh_token是否正确")
            else:
                logger.warning("未配置Pixiv refresh_token，部分功能可能无法使用")
            
            self.base_dir = StarTools.get_data_dir(self.plugin_name)
            # 创建临时目录用于存储下载的图片
            self.temp_dir = self.base_dir / "temp"
            if not self.temp_dir.exists():
                self.temp_dir.mkdir(parents=True, exist_ok=True)
            # 创建持久化目录
            self.persistent_dir = self.base_dir / "persistent"
            if not self.persistent_dir.exists():
                self.persistent_dir.mkdir(parents=True, exist_ok=True)
            logger.info(f"Pid2Pdf插件初始化完成，临时目录: {self.temp_dir}")
            
        except Exception as e:
            logger.error(f"Pid2Pdf插件初始化失败: {e}")

    @filter.command("pid2pdf")
    async def pid_to_pdf(self, event: AstrMessageEvent):
        """根据Pixiv ID下载图片并生成PDF"""
        try:
            # 解析用户输入的PID
            message_parts = event.message_str.strip().split()
            if len(message_parts) < 2:
                yield event.plain_result("请提供Pixiv ID，格式: /pid2pdf <PID>")
                return
            
            pid = message_parts[1].strip()
            if not pid.isdigit():
                yield event.plain_result("Pixiv ID必须是数字")
                return
            #检查本地是否存在PID的PDF文件
            pdf_path = self.persistent_dir / f"pixiv_{pid}.pdf"
            if pdf_path.exists():
                logger.info(f"本地已存在该PID的PDF文件: {pdf_path}")
                # 发送PDF文件
                async for result in self._send_pdf(event, pdf_path, pid):
                    yield result
                return
            
            yield event.plain_result(f"开始获取 Pixiv 作品: {pid}，请稍候...")
            
            # 获取作品详情
            artwork_info = await self._get_artwork_info(pid)
            if not artwork_info:
                yield event.plain_result(f"无法获取PID {pid} 的作品信息")
                return
            
            # 下载图片
            image_paths = await self._download_images(artwork_info, pid)
            if not image_paths:
                yield event.plain_result(f"下载PID {pid} 的图片失败")
                return
            
            # 生成PDF
            pdf_path = await self._create_pdf(image_paths, pid, artwork_info)
            if not pdf_path:
                yield event.plain_result(f"生成PDF失败")
                return
            
            # 发送PDF文件
            async for result in self._send_pdf(event, pdf_path, pid):
                 yield result
            
        except Exception as e:
            logger.error(f"处理PID转PDF时出错: {e}")
            yield event.plain_result(f"处理过程中出现错误: {str(e)}")


    async def _get_artwork_info(self, pid: str) -> dict:
        """获取Pixiv作品信息"""
        try:
            if not self.papi:
                logger.error("Pixiv API未初始化")
                return None
            
            # 获取作品详情
            result = self.papi.illust_detail(pid)
            if result.illust:
                artwork = result.illust
                return {
                    "id": artwork.id,
                    "title": artwork.title,
                    "user": {
                        "id": artwork.user.id,
                        "name": artwork.user.name
                    },
                    "meta_single_page": artwork.meta_single_page,
                    "meta_pages": artwork.meta_pages,
                    "total_view": artwork.total_view,
                    "total_bookmarks": artwork.total_bookmarks,
                    "sanity_level": artwork.sanity_level
                }
            else:
                logger.error(f"未找到PID {pid} 的作品")
                return None
            
        except Exception as e:
            logger.error(f"获取作品信息失败: {e}")
            return None

    async def _download_images(self, artwork_info: dict, pid) -> List[Path]:
        """下载Pixiv图片"""
        try:
            image_paths = []
            temp_download_dir = self.temp_dir / f"{pid}"
            if not temp_download_dir.exists():
                temp_download_dir.mkdir(parents=True, exist_ok=True)
            if artwork_info.get("meta_single_page"):
                # 单图作品
                url = artwork_info["meta_single_page"]["original_image_url"]
                path = await self._download_single_image(url, 0, pid)
                if path:
                    image_paths.append(path)
            elif artwork_info.get("meta_pages"):
                # 多图作品
                for i, page in enumerate(artwork_info["meta_pages"]):
                    url = page["image_urls"]["original"]
                    path = await self._download_single_image(url, i, pid)
                    if path:
                        image_paths.append(path)
            
            logger.info(f"下载了 {len(image_paths)} 张图片")
            return image_paths
            
        except Exception as e:
            logger.error(f"下载图片失败: {e}")
            return []

    async def _download_single_image(self, url: str, index: int, pid) -> Path:
        """下载单张图片"""
        try:
            # 设置请求头
            headers = {
                'Referer': 'https://www.pixiv.net/',
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
            }
            
            # 下载图片
            response = requests.get(url, headers=headers, timeout=30)
            if response.status_code == 200:
                # 确定文件扩展名
                content_type = response.headers.get('content-type', '')
                if 'jpeg' in content_type or 'jpg' in content_type:
                    file_extension = 'jpg'
                elif 'png' in content_type:
                    file_extension = 'png'
                elif 'gif' in content_type:
                    file_extension = 'gif'
                else:
                    # 从URL中获取扩展名
                    file_extension = url.split('.')[-1].split('?')[0]
                    if file_extension not in ['jpg', 'jpeg', 'png', 'gif']:
                        file_extension = 'jpg'  # 默认使用jpg
                
                file_path = self.temp_dir / f"{pid}/image_{index}.{file_extension}"
                with open(file_path, 'wb') as f:
                    f.write(response.content)
                
                logger.info(f"下载图片 {index}: {file_path}")
                return file_path
            else:
                logger.error(f"下载图片失败，状态码: {response.status_code}")
                return None
            
        except Exception as e:
            logger.error(f"下载单张图片失败: {e}")
            return None

    async def _create_pdf(self, image_paths: List[Path], pid: str, artwork_info: dict) -> Path:
        """将图片转换为PDF"""
        try:
            if not image_paths:
                return None
            pdf_path = self.persistent_dir / f"pixiv_{pid}.pdf"
            # 将图片转换为PDF
            with open(pdf_path, 'wb') as f:
                f.write(img2pdf.convert(image_paths))
            logger.info(f"生成PDF: {pdf_path}")
            return pdf_path
            
        except Exception as e:
            logger.error(f"生成PDF失败: {e}")
            return None

    async def _send_pdf(self, event: AstrMessageEvent, pdf_path: Path, pid: str):
        """发送PDF文件给用户"""
        try:
            if pdf_path.exists():
                # 发送文件
                yield event.chain_result([File(file=str(pdf_path),name=f"{pid}.pdf")])
                logger.info(f"PDF文件已生成并发送: {pid}.pdf")
            else:
                yield event.plain_result("PDF文发送失败")
            
        except Exception as e:
            logger.error(f"发送PDF失败: {e}")
            yield event.plain_result(f"发送PDF文件失败: {str(e)}")

    async def _cleanup_temp_files(self):
        """清理临时文件"""
        try:
            if self.temp_dir and self.temp_dir.exists():
                import shutil
                shutil.rmtree(self.temp_dir)
                logger.info("清理临时文件完成")
        except Exception as e:
            logger.error(f"清理临时文件失败: {e}")

    @filter.command("pid_help")
    async def help_command(self, event: AstrMessageEvent):
        """显示插件帮助信息"""
        help_text = """
Pid2Pdf 插件使用说明：

命令格式：
/pid2pdf <Pixiv_ID> - 根据Pixiv ID下载图片并生成PDF

示例：
/pid2pdf 123456789

        """
        yield event.plain_result(help_text.strip())

    @filter.command("pid_config")
    async def config_command(self, event: AstrMessageEvent):
        """显示当前配置状态"""
        config_info = f"""
Pid2Pdf 插件配置状态：

Pixiv API状态: {'已登录' if self.papi and self.refresh_token else '未配置'}
代理设置: {self.proxy if self.proxy else '未设置'}
临时目录: {self.temp_dir if self.temp_dir else '未创建'}

如需配置，请在插件配置文件中设置：
- pixiv_refresh_token: 您的Pixiv refresh_token
- proxy: 代理服务器地址（可选）
        """
        yield event.plain_result(config_info.strip())

    async def terminate(self):
        """插件销毁方法"""
        await self._cleanup_temp_files()
        logger.info("Pid2Pdf插件已销毁")
