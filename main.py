from datetime import datetime, date
from typing import List
from pathlib import Path
import aiohttp
import aiofiles
import asyncio
import time
import random

from astrbot.api.event import filter, AstrMessageEvent, MessageChain
from astrbot.api.star import Context, Star, register, StarTools
from astrbot.api import logger
from astrbot.api.message_components import *

# 引入所需的第三方库
from pixivpy3 import AppPixivAPI
import img2pdf

from .subscription import SubscriptionCenter, SubscriptionData

@register("pid2pdf", "Joker42S", "根据Pixiv ID下载图片并保存为PDF发送", "1.0.3")
class Pid2PdfPlugin(Star):
    def __init__(self, context: Context, config : dict):
        super().__init__(context)
        self.config = config
        self.context = context
        self.papi = None
        self.temp_dir = None
        self.refresh_token = None
        self.proxy = None
        self.reverse_proxy = None
        self.use_reverse_proxy = False
        self.egg_trigger_time = 0
        self.egg_trigger_record_file = None

    async def initialize(self):
        """插件初始化方法"""
        try:
            self.plugin_name = "pid2pdf"
            # 从配置中获取refresh_token和代理设置
            self.refresh_token = self.config.get("refresh_token", "")
            self.proxy = self.config.get("proxy", "")
            self.use_reverse_proxy = self.config.get("use_reverse_proxy", False)
            self.reverse_proxy = self.config.get("reverse_proxy", "")
            self.refresh_interval = self.config.get("refresh_interval", 90)
            self.easter_egg = self.config.get("easter_egg", False)
            self.easter_egg_list = self.config.get("easter_egg_list", [])
            
            # 设置代理（如果配置了）
            _REQUESTS_KWARGS: dict[str, Any] = {
                'proxies': {
                    'https': self.proxy,
                    'http': self.proxy,
                },
                # 'verify': False,       # PAPI use https, an easy way is disable requests SSL verify
            }
            # 初始化Pixiv API
            self.papi = AppPixivAPI(**_REQUESTS_KWARGS)
            # self.papi.set_api_proxy('https://i.pixiv.cat')
            
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
            #读本地文件记录
            self.egg_trigger_record_file = self.persistent_dir / "egg_trigger_record.txt"
            if self.egg_trigger_record_file.exists():
                async with aiofiles.open(str(self.egg_trigger_record_file), 'r') as f:
                    self.egg_trigger_time = await f.read()
                if self.egg_trigger_time.isdigit():
                    self.egg_trigger_time = int(self.egg_trigger_time)
                else:
                    self.egg_trigger_time = 0
            self.sub_center = SubscriptionCenter(str(self.persistent_dir / "subscriptions.json"), self.refresh_interval * 60)
            await self.sub_center.initilize()
            self.sub_center.set_callback(self._handle_sub_update)
            self.sub_center.start_timer()
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
            #发送作品信息
            pid = str(artwork_info["id"])
            title = artwork_info["title"]
            views = artwork_info["total_view"]
            bookmarks = artwork_info["total_bookmarks"]
            # create_date = artwork_info["create_date"][:10]  # 只取日期部分
            is_ai = artwork_info.get("is_ai", False)
            info_text = f"#PID: {pid}\n"
            info_text += f"标题: {title}\n"
            # info_text += f"发布日期: {create_date}\n"
            # info_text += f"浏览: {views} | 收藏: {bookmarks}"
            pages = artwork_info.get("meta_pages")
            if pages:
                info_text += f" | 多图作品，共{len(pages)}张"
            if is_ai:
                info_text += " | AI作品"
            yield event.plain_result(info_text)
            # 生成PDF
            pdf_path = await self._create_pdf(image_paths, pid)
            if not pdf_path:
                yield event.plain_result(f"生成PDF失败")
                return
            
            # 发送PDF文件
            async for result in self._send_pdf(event, pdf_path, pid):
                 yield result
            
        except Exception as e:
            logger.error(f"处理PID转PDF时出错: {e}")
            yield event.plain_result(f"处理过程中出现错误: {str(e)}")

    @filter.command("pid")
    async def pid(self, event: AstrMessageEvent):
        """根据Pixiv ID下载图片并发送"""
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
            img_path = self.temp_dir / f"{pid}"
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
            #发送作品信息
            pid = str(artwork_info["id"])
            title = artwork_info["title"]
            views = artwork_info["total_view"]
            bookmarks = artwork_info["total_bookmarks"]
            # create_date = artwork_info["create_date"][:10]  # 只取日期部分
            is_ai = artwork_info.get("is_ai", False)
            info_text = f"#PID: {pid}\n"
            info_text += f"标题: {title}\n"
            # info_text += f"发布日期: {create_date}\n"
            # info_text += f"浏览: {views} | 收藏: {bookmarks}"
            pages = artwork_info.get("meta_pages")
            if pages:
                info_text += f" | 多图作品，共{len(pages)}张"
            if is_ai:
                info_text += " | AI作品"
            yield event.plain_result(info_text)
            # 发送图片
            async for result in self._send_img(event, img_path, pid):
                yield result
            
        except Exception as e:
            logger.error(f"处理PID出错: {e}")
            yield event.plain_result(f"处理过程中出现错误: {str(e)}")

    async def _get_artwork_info(self, pid: str) -> dict:
        """获取Pixiv作品信息"""
        try:
            if not self.papi:
                logger.error("Pixiv API未初始化")
                return None

            # 获取作品详情
            for i in range(3):
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
                    logger.info("尝试重新登录Pixiv")
                    self.papi.auth(refresh_token=self.refresh_token)
                    await asyncio.sleep(1)
        except Exception as e:
            logger.error(f"获取作品信息失败: {e}")
        logger.info(f"未找到PID {pid} 的作品")
        return None

    async def _download_images(self, artwork_info: dict, pid, max_num = 0) -> List[Path]:
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
                download_num = 0
                for i, page in enumerate(artwork_info["meta_pages"]):
                    url = page["image_urls"]["original"]
                    path = await self._download_single_image(url, i, pid)
                    if path:
                        image_paths.append(path)
                        download_num += 1
                    if max_num > 0 and download_num >= max_num:
                        break

            
            logger.info(f"下载了 {len(image_paths)} 张图片")
            return image_paths
            
        except Exception as e:
            logger.error(f"下载图片失败: {e}")
            return []

    async def _download_single_image(self, url: str, index: int, pid, modify_hash = True) -> Path:
        """下载单张图片"""
        for file_extension in ['jpg', 'png', 'gif']:
            file_path = self.temp_dir / f"{pid}/image_{index}.{file_extension}"
            if file_path.exists():
                ## 图片已存在，无需重复下载
                return file_path
        try:
            # 设置请求头
            headers = {
                'Referer': 'https://www.pixiv.net/',
                'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
            }
            
            # 使用国内反代
            proxy = self.proxy
            if self.use_reverse_proxy and self.reverse_proxy:
                url = url.replace('i.pximg.net', 'i.pixiv.re')
                proxy = None
            # 下载图片
            async with aiohttp.ClientSession() as session:
                async with session.get(url, headers=headers, timeout=30, proxy=proxy) as response:
                    if response.status == 200:
                        # Determine file extension from content type
                        content_type = response.headers.get('content-type', '')
                        if 'jpeg' in content_type or 'jpg' in content_type:
                            file_extension = 'jpg'
                        elif 'png' in content_type:
                            file_extension = 'png'
                        elif 'gif' in content_type:
                            file_extension = 'gif'
                        else:
                            # Get extension from URL
                            file_extension = url.split('.')[-1].split('?')[0]
                            if file_extension not in ['jpg', 'jpeg', 'png', 'gif']:
                                file_extension = 'jpg'  # Default to jpg
                        
                        file_path = self.temp_dir / f"{pid}/image_{index}.{file_extension}"
                        
                        img_data = await response.read()
                        if modify_hash:
                            img_data = await _image_obfus(img_data)
                        with open(file_path, 'wb') as f:
                            f.write(img_data)
                        
                        logger.info(f"下载图片 {index}: {file_path}")
                        return file_path
                    else:
                        logger.error(f"下载图片失败，状态码: {response.status}")
                        return None
            
        except Exception as e:
            logger.error(f"下载单张图片失败: {e}")
            return None

    async def _create_pdf(self, image_paths: List[Path], pdf_name: str) -> Path:
        """将图片转换为PDF"""
        try:
            if not image_paths:
                return None
            pdf_path = self.persistent_dir / f"pixiv_{pdf_name}.pdf"
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

    async def _send_img(self, event: AstrMessageEvent, img_path: Path, pid: str, fake_record = False):
        """发送图片文件给用户"""
        try:
            if img_path.exists():
                chain = [Plain(f'PID：{pid}')]
                for img in img_path.iterdir():
                    if not img.is_file():
                        continue
                    chain.append(Image.fromFileSystem(str(img.absolute())))
                if fake_record:
                    node = Node(
                            uin=905617992,
                            name="Soulter",
                            content=chain
                        )
                    yield event.chain_result([node])
                else:
                    yield event.chain_result(chain)
                logger.info(f"图片已送: {pid}")
                yield event.plain_result("图片已发送，如果看不到，就是被企鹅的大手截胡了，改用/pid2pdf发送吧！")
            else:
                yield event.plain_result("图片发送失败")
            
        except Exception as e:
            logger.error(f"发送图片失败: {e}")
            yield event.plain_result(f"发送图片失败: {str(e)}")


    async def _cleanup_temp_files(self):
        """清理临时文件"""
        try:
            if self.temp_dir and self.temp_dir.exists():
                import shutil
                # shutil.rmtree(self.temp_dir)
                logger.info("清理临时文件完成")
        except Exception as e:
            logger.error(f"清理临时文件失败: {e}")

    @filter.command("pixiv_ranking")
    async def pixiv_ranking(self, event: AstrMessageEvent):
        """获取Pixiv排行榜作品并发送"""
        try:
            # 解析用户输入的参数
            message_parts = event.message_str.strip().split()
            
            # 设置默认参数
            mode = "day"  # 默认日榜
            content = "all"  # 默认全部内容
            date = None  # 默认当前日期
            count = 5  # 默认获取5个作品
            
            # 解析参数
            if len(message_parts) >= 2:
                # 第一个参数是排行榜类型
                mode_input = message_parts[1].lower()
                if mode_input in ["day", "week", "month", "day_male", "week_original", "day_manga", "day_r18", "week_r18", "day_ai", "day_r18_ai"]:
                    mode = mode_input
                elif mode_input.isdigit():
                    count = min(int(mode_input), 10)  # 最多10个作品
            
            if len(message_parts) >= 3:
                # 第二个参数可能是数量
                if message_parts[2].isdigit():
                    count = min(int(message_parts[2]), 10)

            # 应用R18过滤设置
            r18_mode = self.config.get("r18_mode", "过滤 R18")
            if r18_mode == "过滤 R18":
                if mode in ["day", "week", "month"]:
                    pass  # 保持原模式，这些模式默认不包含R18
                else:
                    mode = "day"  # 强制使用日榜
            
            for result in self._process_ranking_request(event, mode, date, count):
                yield result

        except Exception as e:
            logger.error(f"获取Pixiv排行榜时出错: {e}")
            yield event.plain_result(f"获取排行榜时出现错误: {str(e)}")

    async def _process_ranking_request(self, event: AstrMessageEvent, mode: str, date: str, count: int):
        """Process and send Pixiv ranking request"""
        yield event.plain_result(f"正在获取Pixiv {mode} 排行榜前 {count} 个作品，请稍候...")
        
        # Get ranking data
        ranking_data = await self._get_ranking(mode, date, count)
        if not ranking_data:
            yield event.plain_result("获取排行榜失败，请检查网络连接或稍后重试")
            return
        
        # Send artwork info and images
        async for result in self._send_ranking_results(event, ranking_data, count, mode):
            yield result
    
    async def _get_ranking(self, mode: str = "day", date: str = None, count: int = 5) -> list:
        """获取Pixiv排行榜数据"""
        try:
            if not self.papi:
                logger.error("Pixiv API未初始化")
                return None
            
            # 获取排行榜
            for i in range(3):
                result = self.papi.illust_ranking(mode=mode, date=date)
                if result.illusts:
                    break
                else:
                    logger.info("尝试重新登录Pixiv")
                    self.papi.auth(refresh_token=self.refresh_token)
                    await asyncio.sleep(1)
            if result.illusts:
                # 应用AI过滤设置
                ai_filter_mode = self.config.get("ai_filter_mode", "显示 AI 作品")
                filtered_illusts = []
                
                for illust in result.illusts[:count * 2]:  # 获取更多以便过滤
                    # AI作品过滤
                    is_ai = hasattr(illust, 'illust_ai_type') and illust.illust_ai_type == 2
                    
                    if ai_filter_mode == "过滤 AI 作品" and is_ai:
                        continue
                    elif ai_filter_mode == "仅 AI 作品" and not is_ai:
                        continue
                    
                    filtered_illusts.append({
                        "id": illust.id,
                        "title": illust.title,
                        "user": {
                            "id": illust.user.id,
                            "name": illust.user.name
                        },
                        "meta_single_page": illust.meta_single_page,
                        "meta_pages": illust.meta_pages,
                        "total_view": illust.total_view,
                        "total_bookmarks": illust.total_bookmarks,
                        "sanity_level": illust.sanity_level,
                        "is_ai": is_ai
                    })
                    
                    if len(filtered_illusts) >= count:
                        break
                
                return filtered_illusts[:count]
            else:
                logger.error("排行榜数据为空")
                return None
                
        except Exception as e:
            logger.error(f"获取排行榜数据失败: {e}")
            return None
    
    async def _send_ranking_results(self, event: AstrMessageEvent, ranking_data: list, count: int, mode: str):
        """发送排行榜结果"""
        try:
            pdf_img_paths = []
            combined_infos = ["作品信息：\n"]
            is_r18 = mode in ["day_r18", "week_r18", "day_r18_ai"]
            for i, artwork in enumerate(ranking_data, 1):
                pid = str(artwork["id"])
                title = artwork["title"]
                author = artwork["user"]["name"]
                views = artwork["total_view"]
                bookmarks = artwork["total_bookmarks"]
                is_ai = artwork.get("is_ai", False)
                
                # 构建作品信息
                info_text = f"#{i} PID: {pid}\n"
                info_text += f"标题: {title}\n"
                info_text += f"作者: {author}\n"
                # info_text += f"浏览: {views} | 收藏: {bookmarks}"
                pages = artwork.get("meta_pages")
                if pages:
                    info_text += f" | 多图作品，共{len(pages)}张"
                if is_ai:
                    info_text += " | AI作品"
                if is_r18:
                    combined_infos.append(info_text + "\n\n")
                else:
                    yield event.plain_result(info_text)
                
                # 下载并发送第一张图片作为预览
                try:
                    # 检查本地是否已有图片
                    img_dir = self.temp_dir / f"{pid}"
                    if img_dir.exists() and any(img_dir.iterdir()):
                        # 发送已有的图片
                        first_img = next(img_dir.iterdir())
                        if is_r18:
                            pdf_img_paths.append(str(first_img.absolute()))
                        else:
                            yield event.chain_result([Image.fromFileSystem(str(first_img.absolute()))])
                    else:
                        # 下载第一张图片
                        image_paths = await self._download_images(artwork, pid, 1)
                        if image_paths:
                            if is_r18:
                                pdf_img_paths.append(str(image_paths[0].absolute()))
                            else:
                                yield event.chain_result([Image.fromFileSystem(str(image_paths[0].absolute()))])
                        else:
                            yield event.plain_result("图片下载失败")
                except Exception as e:
                    logger.error(f"发送排行榜图片失败: {e}")
                    yield event.plain_result(f"图片发送失败: {str(e)}")
                
                # 添加分隔
                # if i < len(ranking_data):
                #     yield event.plain_result("---")
            if len(pdf_img_paths) > 0:
                pdf_name = f"{mode}_{date.today()}"
                pdf_path = await self._create_pdf(pdf_img_paths, pdf_name)
                if not pdf_path:
                    yield event.plain_result(f"生成PDF失败")
                    return
                yield event.chain_result([File(file=str(pdf_path),name=f"{pdf_name}.pdf")])
                chain = []
                for info in combined_infos:
                    chain.append(Plain(info))
                node = Node(
                            uin=905617992,
                            name="Soulter",
                            content=chain
                        )
                yield event.chain_result([node])
        except Exception as e:
            logger.error(f"发送排行榜结果失败: {e}")
            yield event.plain_result(f"发送结果时出现错误: {str(e)}")

    @filter.command("puid")
    async def puid(self, event: AstrMessageEvent):
        """根据画师UID下载最新作品"""
        try:
            # 解析用户输入的参数
            message_parts = event.message_str.strip().split()
            if len(message_parts) < 2:
                yield event.plain_result("请提供画师UID，格式: /puid <UID> [数量]")
                return
            
            uid = message_parts[1].strip()
            if not uid.isdigit():
                yield event.plain_result("画师UID必须是数字")
                return
            
            # 解析作品数量参数
            count = 5  # 默认5个作品
            if len(message_parts) >= 3:
                try:
                    count = int(message_parts[2])
                    count = min(max(count, 1), 10)  # 限制在1-10之间
                except ValueError:
                    yield event.plain_result("作品数量必须是数字")
                    return
            
            yield event.plain_result(f"开始获取画师 {uid} 的最新 {count} 个作品，请稍候...")
            
            # 获取画师信息和作品列表
            artist_works = await self._get_artist_works(uid, count)
            if not artist_works:
                yield event.plain_result(f"无法获取画师 {uid} 的作品信息")
                return
            
            artist_name = artist_works["artist_name"]
            works = artist_works["works"]
            
            if not works or len(works) == 0:
                yield event.plain_result(f"画师 {artist_name} (UID: {uid}) 没有符合过滤条件的作品")
                return
            # 发送画师信息
            yield event.plain_result(f"画师: {artist_name} (UID: {uid})\n共找到 {len(works)} 个作品")

            # 发送画师作品
            async for result in self._send_artist_works(event, artist_works, uid, count):
                yield result
        except Exception as e:
            logger.error(f"处理画师UID时出错: {e}")
            yield event.plain_result(f"处理过程中出现错误: {str(e)}")
    
    async def _get_artist_works(self, uid: str, count: int = 5) -> list:
        """获取画师的最新作品"""
        try:
            if not self.papi:
                logger.error("Pixiv API未初始化")
                return None
            
            # 获取画师信息
            for i in range(3):
                user_detail = self.papi.user_detail(uid)
                if user_detail.user:
                    break
                else:
                    logger.info("尝试重新登录Pixiv")
                    self.papi.auth(refresh_token=self.refresh_token)
                    await asyncio.sleep(1)
            if not user_detail.user:
                logger.error(f"未找到画师 {uid}")
                return None
            
            artist_name = user_detail.user.name
            logger.info(f"找到画师: {artist_name} (UID: {uid})")
            
            # 获取画师的插画作品
            for i in range(3):
                result = self.papi.user_illusts(uid)
                if result.illusts is not None:
                    break
                else:
                    logger.info("尝试重新登录Pixiv")
                    self.papi.auth(refresh_token=self.refresh_token)
                    await asyncio.sleep(1)
            if not result.illusts:
                logger.error(f"画师 {uid} 没有作品")
                return None
            
            # 应用过滤设置
            r18_mode = self.config.get("r18_mode", "过滤 R18")
            ai_filter_mode = self.config.get("ai_filter_mode", "显示 AI 作品")
            
            filtered_works = []
            for illust in result.illusts:
                # R18过滤
                if r18_mode == "过滤 R18" and illust.sanity_level >= 4:
                    continue
                elif r18_mode == "仅 R18" and illust.sanity_level < 4:
                    continue
                
                # AI作品过滤
                is_ai = hasattr(illust, 'illust_ai_type') and illust.illust_ai_type == 2
                if ai_filter_mode == "过滤 AI 作品" and is_ai:
                    continue
                elif ai_filter_mode == "仅 AI 作品" and not is_ai:
                    continue
                
                filtered_works.append({
                    "id": illust.id,
                    "title": illust.title,
                    "user": {
                        "id": illust.user.id,
                        "name": illust.user.name
                    },
                    "meta_single_page": illust.meta_single_page,
                    "meta_pages": illust.meta_pages,
                    "total_view": illust.total_view,
                    "total_bookmarks": illust.total_bookmarks,
                    "sanity_level": illust.sanity_level,
                    # "create_date": illust.create_date,
                    "is_ai": is_ai
                })
                
                if len(filtered_works) >= count:
                    break
            
            return {
                "artist_name": artist_name,
                "artist_uid": uid,
                "works": filtered_works[:count]
            }
            
        except Exception as e:
            logger.error(f"获取画师作品失败: {e}")
            return None
    
    async def _send_artist_works(self, event: AstrMessageEvent, artist_data: dict, uid: str, count: int):
        """发送画师作品结果"""
        try:
            works = artist_data["works"]
            for i, artwork in enumerate(works, 1):
                pid = str(artwork["id"])
                title = artwork["title"]
                views = artwork["total_view"]
                bookmarks = artwork["total_bookmarks"]
                # create_date = artwork["create_date"][:10]  # 只取日期部分
                is_ai = artwork.get("is_ai", False)
                
                # 构建作品信息
                info_text = f"#{i} PID: {pid}\n"
                info_text += f"标题: {title}\n"
                # info_text += f"发布日期: {create_date}\n"
                # info_text += f"浏览: {views} | 收藏: {bookmarks}"
                pages = artwork.get("meta_pages")
                if pages:
                    info_text += f" | 多图作品，共{len(pages)}张"
                if is_ai:
                    info_text += " | AI作品"
                
                yield event.plain_result(info_text)
                
                # 下载并发送第一张图片作为预览
                try:
                    # 检查本地是否已有图片
                    img_dir = self.temp_dir / f"{pid}"
                    if img_dir.exists() and any(img_dir.iterdir()):
                        # 发送已有的图片
                        first_img = next(img_dir.iterdir())
                        yield event.chain_result([Image.fromFileSystem(str(first_img.absolute()))])
                    else:
                        # 下载第一张图片
                        image_paths = await self._download_images(artwork, pid, 1)
                        if image_paths:
                            yield event.chain_result([Image.fromFileSystem(str(image_paths[0].absolute()))])
                        else:
                            yield event.plain_result("图片下载失败")
                            
                except Exception as e:
                    logger.error(f"发送画师作品图片失败: {e}")
                    yield event.plain_result(f"图片发送失败: {str(e)}")
                
                # 添加分隔
                # if i < len(works):
                #     yield event.plain_result("---")
                    
        except Exception as e:
            logger.error(f"发送画师作品结果失败: {e}")
            yield event.plain_result(f"发送结果时出现错误: {str(e)}")

    @filter.command("订阅画师")
    async def add_sub(self, event: AstrMessageEvent):
        """订阅画师最新作品"""
        # 解析用户输入的参数
        message_parts = event.message_str.strip().split()
        if len(message_parts) < 2:
            yield event.plain_result("请提供画师UID，格式: /订阅画师 123456")
            return
        
        uid = message_parts[1].strip()
        if not uid.isdigit():
            yield event.plain_result("画师UID必须是数字")
            return
        group_id = event.unified_msg_origin
        
        # 添加订阅
        await self.sub_center.add_subscription(uid, group_id)
        yield event.plain_result(f"成功订阅画师 UID: {uid} 的最新作品，使用命令 ""刷新订阅"" 可立即获取最新作品")

    @filter.command("删除订阅")
    async def remove_sub(self, event: AstrMessageEvent):
        """删除订阅"""
        # 解析用户输入的参数
        message_parts = event.message_str.strip().split()
        if len(message_parts) < 2:
            yield event.plain_result("请提供画师UID，格式: /删除订阅 123456")
            return
        
        uid = message_parts[1].strip()
        if not uid.isdigit():
            yield event.plain_result("画师UID必须是数字")
            return
        group_id = event.unified_msg_origin
        
        # 添加订阅
        sucess = await self.sub_center.remove_subscription(uid, group_id)
        if sucess:
            yield event.plain_result(f"删除订阅成功")
        else:
            yield event.plain_result(f"删除订阅失败")

    @filter.command("/刷新订阅")
    async def refresh_subscriptions(self, event: AstrMessageEvent):
        await self.sub_center.manual_refresh()

    async def _handle_sub_update(self, sub_data_list: list[SubscriptionData]):
        logger.info("开始更新订阅")
        try:
            for sub_data in sub_data_list:
                user_id = sub_data["user_id"]
                sub_groups = sub_data["sub_groups"]
                last_updated_id = sub_data["last_updated_id"]
                # 获取最新作品
                artist_works = await self._get_artist_works(user_id, 10)
                if not artist_works:
                    logger.error(f"无法获取画师 {user_id} 的作品信息")
                    continue
                artist_name = artist_works["artist_name"]
                works = artist_works["works"] or []
                works.sort(key=lambda x: int(x["id"]), reverse=True)
                new_works = []
                new_updated_id = int(last_updated_id)
                for artwork_info in works:
                    new_updated_id = max(new_updated_id, int(artwork_info["id"]))
                    if int(artwork_info["id"]) <= int(last_updated_id):
                        break
                    new_works.append(artwork_info)
                new_works = new_works[:5]
                # 更新最后作品ID
                if new_updated_id > int(last_updated_id):
                    await self.sub_center.renew_last_updated_id(user_id, new_updated_id)
                if len(new_works) == 0:
                    logger.info(f"画师 {artist_name} (UID: {user_id}) 没有符合过滤条件的新作品")
                    continue
                for group_id in sub_groups:
                    await self.context.send_message(group_id, MessageChain().message(f"画师: {artist_name} (UID: {user_id})\n有 {len(new_works)} 个新作品"))
                for artwork_info in new_works:
                    #发送作品信息
                    pid = str(artwork_info["id"])
                    title = artwork_info["title"]
                    views = artwork_info["total_view"]
                    bookmarks = artwork_info["total_bookmarks"]
                    # create_date = artwork_info["create_date"][:10]  # 只取日期部分
                    is_ai = artwork_info.get("is_ai", False)
                    info_text = f"#PID: {pid}\n"
                    info_text += f"标题: {title}\n"
                    # info_text += f"发布日期: {create_date}\n"
                    # info_text += f"浏览: {views} | 收藏: {bookmarks}"
                    # pages = artwork_info.get("meta_pages")
                    # if pages:
                        # info_text += f" | 多图作品，共{len(pages)}张"
                    if is_ai:
                        info_text += "AI作品"
                    for group_id in sub_groups:
                        await self.context.send_message(group_id, MessageChain().message(info_text))

                    # 下载图片
                    image_paths = await self._download_images(artwork_info, pid)
                    if not image_paths:
                        logger.info(f"下载PID {pid} 的图片失败")
                    else:
                        img_msg_chain = MessageChain()
                        for img in image_paths:
                            img_msg_chain = img_msg_chain.file_image(str(img.absolute()))
                        for group_id in sub_groups:
                            try:
                                await self.context.send_message(group_id, img_msg_chain)
                            except Exception as e:
                                logger.error(f"发送订阅图片失败，{e}")
        except Exception as e:
            logger.error(f"更新订阅时出错： {e}")



    @filter.event_message_type(filter.EventMessageType.ALL)
    async def handle_text_event(self, event: AstrMessageEvent):
        """简易命令： 今日色图 今日ai色图 今日排行榜 今日ai图 刷新订阅"""
        if event.message_str == "今日色图":
            async for result in self._process_ranking_request(event, mode = "day_r18", date = None, count = 10):
                yield result
        elif event.message_str == "今日ai色图":
            async for result in self._process_ranking_request(event, mode = "day_r18_ai", date = None, count = 10):
                yield result
        elif event.message_str == "今日排行榜":
            async for result in self._process_ranking_request(event, mode = "day_male", date = None, count = 10):
                yield result
        elif event.message_str == "今日ai图":
            async for result in self._process_ranking_request(event, mode = "day_ai", date = None, count = 10):
                yield result
        elif event.message_str == "刷新订阅":
            await self.sub_center.manual_refresh()
        #彩蛋 随机排行榜 超过一天后可再次触发，几率10%
        elif self.easter_egg and int(datetime.now().timestamp()) - self.egg_trigger_time > 86400 and random.random() < 0.1:
            self.egg_trigger_time = int(datetime.now().timestamp())
            async with aiofiles.open(str(self.egg_trigger_record_file), "w") as f:
                await f.write(str(self.egg_trigger_time))
            rank_name = self.easter_egg_list[random.randint(0, len(self.easter_egg_list)-1)]
            yield event.plain_result(f"你触发了今天的彩蛋！即将发送：{rank_name}")
            if rank_name == "今日色图":
                async for result in self._process_ranking_request(event, mode = "day_r18", date = None, count = 10):
                    yield result
            elif rank_name == "今日ai色图":
                async for result in self._process_ranking_request(event, mode = "day_r18_ai", date = None, count = 10):
                    yield result
            elif rank_name == "今日排行榜":
                async for result in self._process_ranking_request(event, mode = "day_male", date = None, count = 10):
                    yield result
            elif rank_name == "今日ai图":
                async for result in self._process_ranking_request(event, mode = "day_ai", date = None, count = 10):
                    yield result


    
    @filter.command("pid_help")
    async def help_command(self, event: AstrMessageEvent):
        """显示插件帮助信息"""
        help_text = """
Pid2Pdf 插件使用说明：

命令格式：
/pid2pdf <Pixiv_ID> - 根据Pixiv ID下载图片并生成PDF
/pid <Pixiv_ID> - 根据Pixiv ID下载图片并发送
/pixiv_ranking [类型] [数量] - 获取Pixiv排行榜作品
/puid <UID> [数量] - 根据画师UID下载最新作品

排行榜类型：
- day: 日榜（默认）
- week: 周榜
- month: 月榜
- day_male: 男性向日榜
- week_original: 原创周榜
- day_manga: 漫画日榜
- day_r18: R18日榜
- week_r18: R18周榜
- day_ai: AI作品榜
- day_r18_ai: AI作品榜

示例：
/pid2pdf 123456789
/pid 123456789
/pixiv_ranking day 3
/pixiv_ranking week
/pixiv_ranking 5
/puid 12345678 3
/puid 87654321

        """
        yield event.plain_result(help_text.strip())

    @filter.command("pid_config")
    async def config_command(self, event: AstrMessageEvent):
        """显示当前配置状态"""
        config_info = f"""
Pid2Pdf 插件配置状态：

Pixiv API状态: {'已登录' if self.papi and self.refresh_token else '未配置'}
代理设置: {self.proxy if self.proxy else '未设置'}

如需配置，请在插件配置文件中设置：
- pixiv_refresh_token: 您的Pixiv refresh_token
- proxy: 代理服务器地址（可选）
        """
        yield event.plain_result(config_info.strip())

    async def terminate(self):
        """插件销毁方法"""
        await self._cleanup_temp_files()
        await self.sub_center.cleanup()
        logger.info("Pid2Pdf插件已销毁")

async def _image_obfus(img_data):
    """破坏图片哈希"""
    from PIL import Image as ImageP
    from io import BytesIO
    import random

    try:
        with BytesIO(img_data) as input_buffer:
            with ImageP.open(input_buffer) as img:
                if img.mode != "RGB":
                    img = img.convert("RGB")

                width, height = img.size
                pixels = img.load()

                points = []
                for _ in range(3):
                    while True:
                        x = random.randint(0, width - 1)
                        y = random.randint(0, height - 1)
                        if (x, y) not in points:
                            points.append((x, y))
                            break

                for x, y in points:
                    r, g, b = pixels[x, y]

                    r_change = random.choice([-1, 1])
                    g_change = random.choice([-1, 1])
                    b_change = random.choice([-1, 1])

                    new_r = max(0, min(255, r + r_change))
                    new_g = max(0, min(255, g + g_change))
                    new_b = max(0, min(255, b + b_change))

                    pixels[x, y] = (new_r, new_g, new_b)

                with BytesIO() as output:
                    img.save(output, format="PNG")
                    return output.getvalue()

    except Exception as e:
        logger.warning(f"破坏图片哈希时发生错误: {str(e)}")
        return img_data
    