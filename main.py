from datetime import datetime, date
from typing import Any, List
from pathlib import Path
import aiohttp
import aiofiles
import asyncio
import re
import random

from astrbot.api.event import filter, AstrMessageEvent, MessageChain
from astrbot.api.star import Context, Star, register, StarTools
from astrbot.api import logger
from astrbot.api.message_components import *

# 引入所需的第三方库
from pixivpy3 import AppPixivAPI
import img2pdf

from .subscription import SubscriptionCenter, SubscriptionData

# 排行榜模式白名单，与 README / /pid_help 保持一致。
# 注意 pixivpy3 的 _MODE 类型别名已过时（不含 day_ai 系列），
# 但 App API 实际接受下面这些模式，mode 是原样透传给接口的。
# 字典同时作为模式的中文说明，/pid_help 直接从它生成，避免两边脱节。
RANKING_MODE_LABELS = {
    "day": "日榜（默认）",
    "week": "周榜",
    "month": "月榜",
    "day_male": "男性向日榜",
    "day_female": "女性向日榜",
    "week_original": "原创周榜",
    "week_rookie": "新人周榜",
    "day_manga": "漫画日榜",
    "day_r18": "R18 日榜",
    "day_male_r18": "R18 男性向日榜",
    "day_female_r18": "R18 女性向日榜",
    "week_r18": "R18 周榜",
    "week_r18g": "R18G 周榜",
    "day_ai": "AI 作品日榜",
    "day_r18_ai": "R18 AI 作品日榜",
    "week_r18_ai": "R18 AI 作品周榜",
}

RANKING_MODES = tuple(RANKING_MODE_LABELS)

# 属于 R18 的排行榜模式：这些才需要走 PDF 通道，其它模式不应该被 R18 设置改写
R18_RANKING_MODES = frozenset(
    {
        "day_r18",
        "day_male_r18",
        "day_female_r18",
        "week_r18",
        "week_r18g",
        "day_r18_ai",
        "week_r18_ai",
    }
)


def _as_bool(value: Any, default: bool = False) -> bool:
    """把配置项转成 bool。

    _conf_schema.json 里曾经把 bool 类型的 default 写成字符串 "false"，
    而 AstrBot 是把 default 原样写进配置的，所以老用户的配置里可能存着
    字符串 "false" —— 它是真值，不能直接 if。
    """
    if isinstance(value, bool):
        return value
    if value is None:
        return default
    if isinstance(value, str):
        return value.strip().lower() in ("1", "true", "yes", "on")
    return bool(value)


def _as_int(value: Any, default: int) -> int:
    """把配置项转成 int，无法转换时回退到 default。

    同样是为了兼容历史配置：schema 里 int 类型的 default 曾写成字符串 "90"。
    """
    try:
        return int(value)
    except (TypeError, ValueError):
        logger.warning(f"配置项 {value!r} 不是合法整数，回退为 {default}")
        return default


def _image_sort_key(path: Path) -> tuple:
    """按文件名里的数字排序，保证 image_2.jpg 排在 image_10.jpg 前面。"""
    match = re.search(r"(\d+)", path.stem)
    return (int(match.group(1)) if match else 0, path.name)


def _sorted_images(directory: Path) -> List[Path]:
    """列出目录里的图片文件并按页码排序。

    直接用 iterdir() 拿到的是文件系统顺序，多图作品的发送顺序和预览图
    都会错乱，所以这里统一排一次序。
    """
    if not directory or not directory.exists():
        return []
    return sorted(
        (p for p in directory.iterdir() if p.is_file()),
        key=_image_sort_key,
    )


def _is_ai_illust(illust: Any) -> bool:
    """判断作品是否是 AI 生成。

    pixivpy3 的 JsonDict 对不存在的键返回 None 而不是抛 AttributeError，
    所以这里直接比较即可（字段缺失时结果是 False）。
    """
    return getattr(illust, "illust_ai_type", None) == 2


# 群里直接发这几个词就能触发的简易命令 -> 对应的排行榜模式
SIMPLE_COMMAND_MODES = {
    "今日色图": "day_r18",
    "今日ai色图": "day_r18_ai",
    "今日排行榜": "day_male",
    "今日ai图": "day_ai",
}

# Pixiv 链接识别。允许省略协议头，也允许带语言前缀（/en/、/zh-tw/）。
_PIXIV_LANG_PREFIX = r"(?:[a-z]{2}(?:-[a-z]{2})?/)?"
PIXIV_ARTWORK_PATTERNS = (
    re.compile(rf"pixiv\.net/{_PIXIV_LANG_PREFIX}artworks/(\d+)", re.IGNORECASE),
    re.compile(rf"pixiv\.net/{_PIXIV_LANG_PREFIX}i/(\d+)", re.IGNORECASE),
    re.compile(
        r"pixiv\.net/member_illust\.php\?[^\s]*?illust_id=(\d+)", re.IGNORECASE
    ),
)
PIXIV_USER_RE = re.compile(rf"pixiv\.net/{_PIXIV_LANG_PREFIX}users/(\d+)", re.IGNORECASE)

# 标签太多会刷屏，超过就截断
MAX_TAGS_IN_INFO = 15


def _extract_pixiv_artwork_id(text: str) -> str:
    """从文本里找出 Pixiv 作品 ID，找不到返回 None。"""
    for pattern in PIXIV_ARTWORK_PATTERNS:
        match = pattern.search(text)
        if match:
            return match.group(1)
    return None


def _extract_pixiv_user_id(text: str) -> str:
    """从文本里找出 Pixiv 画师 UID，找不到返回 None。"""
    match = PIXIV_USER_RE.search(text)
    return match.group(1) if match else None


# 本插件注册的指令名。AstrBot 的 waking 阶段会把 wake_prefix（默认 "/"）从
# event.message_str 里剥掉再交给 handler，所以这里比较的是剥掉前缀后的第一个 token。
PLUGIN_COMMAND_NAMES = frozenset(
    {
        "pid2pdf",
        "pid",
        "pixiv_ranking",
        "puid",
        "订阅画师",
        "删除订阅",
        "刷新订阅",
        "pid_help",
        "pid_config",
    }
)


def _looks_like_plugin_command(text: str) -> bool:
    """这条消息是不是本插件的指令调用。

    用于让链接识别跳过指令消息，避免 /pid2pdf <链接> 这类写法既被指令处理、
    又被链接识别处理，导致重复发送。
    """
    if not text:
        return False
    return text.split(maxsplit=1)[0] in PLUGIN_COMMAND_NAMES


def _parse_pid_arg(raw: str) -> str:
    """指令参数可以是纯数字 PID，也可以是 Pixiv 作品链接。"""
    raw = (raw or "").strip()
    if raw.isdigit():
        return raw
    return _extract_pixiv_artwork_id(raw)


def _parse_uid_arg(raw: str) -> str:
    """指令参数可以是纯数字 UID，也可以是 Pixiv 画师链接。"""
    raw = (raw or "").strip()
    if raw.isdigit():
        return raw
    return _extract_pixiv_user_id(raw)


def _is_r18_artwork(tags: Any) -> bool:
    """作品是否带 R-18 / R-18G 标签。

    这里用 tag 的原始 name 判断，不用 translated_name，避免翻译改写标签名；
    同时兼容 tag 是字符串的极端情况。
    """
    for tag in tags or []:
        name = tag if isinstance(tag, str) else getattr(tag, "name", None)
        if name in ("R-18", "R-18G"):
            return True
    return False


def _format_tags(tags: Any, limit: int = MAX_TAGS_IN_INFO) -> str:
    """把 Pixiv 的标签列表拼成一行文本，优先用翻译后的名字。"""
    names: List[str] = []
    for tag in tags or []:
        if isinstance(tag, str):
            name = tag
        else:
            name = getattr(tag, "translated_name", None) or getattr(tag, "name", None)
        if name and name not in names:
            names.append(str(name))
    if not names:
        return ""
    if len(names) > limit:
        names = names[:limit] + ["…"]
    return "、".join(names)


def _format_artwork_info(
    artwork: dict,
    index: int = None,
    include_tags: bool = False,
    include_r18: bool = False,
) -> str:
    """拼装作品信息文本。

    /pid、/pid2pdf、排行榜共用这一份格式，避免各处各写一遍导致显示不一致。
    index 不为空时输出 "#1 PID: xxx"，否则输出 "#PID: xxx"。
    """
    prefix = f"#{index} " if index is not None else "#"
    info = f"{prefix}PID: {artwork.get('id')}\n"
    info += f"标题: {artwork.get('title')}\n"
    user = artwork.get("user") or {}
    info += f"作者: {user.get('name')}({user.get('id')})"

    flags: List[str] = []
    pages = artwork.get("meta_pages")
    if pages:
        flags.append(f"多图作品，共{len(pages)}张")
    if artwork.get("is_ai", False):
        flags.append("AI作品")
    if include_r18 and _is_r18_artwork(artwork.get("tags")):
        flags.append("R18/R18G作品")
    if flags:
        info += "\n" + " | ".join(flags)

    if include_tags:
        tag_line = _format_tags(artwork.get("tags"))
        if tag_line:
            info += f"\n标签: {tag_line}"
    return info


def _total_pages(artwork: dict) -> int:
    """作品总页数。单图作品记 1 页，拿不到信息记 0。"""
    pages = artwork.get("meta_pages") or []
    if pages:
        return len(pages)
    return 1 if artwork.get("meta_single_page") else 0


def _is_partial(artwork: dict, image_paths: list) -> bool:
    """实际拿到的图片是否少于作品总页数（即只能当预览用）。"""
    total = _total_pages(artwork)
    return bool(total) and len(image_paths) < total


@register("pid2pdf", "Joker42S", "根据Pixiv ID下载图片并保存为PDF发送", "1.0.5")
class Pid2PdfPlugin(Star):
    def __init__(self, context: Context, config : dict):
        super().__init__(context)
        self.config = config
        self.context = context
        self.papi = None
        # 这些属性在 initialize() 里才会被真正赋值。先在构造函数里给一份
        # 安全默认值，这样 initialize() 半路失败时 terminate() 之类的地方
        # 不会因为属性不存在而抛 AttributeError。
        self.plugin_name = "pid2pdf"
        self.base_dir = None
        self.temp_dir = None
        self.persistent_dir = None
        self.sub_center = None
        self.refresh_token = None
        self.proxy = None
        self.reverse_proxy = None
        self.use_reverse_proxy = False
        self.refresh_interval = 90
        self.easter_egg = False
        self.easter_egg_list = []
        self.enable_subscription = False
        self.max_update_limit = 10
        self.egg_trigger_time = 0
        self.egg_trigger_record_file = None

    async def initialize(self):
        """插件初始化方法"""
        try:
            # 从配置中获取refresh_token和代理设置
            self.refresh_token = self.config.get("refresh_token", "") or ""
            self.proxy = self.config.get("proxy", "") or ""
            self.use_reverse_proxy = _as_bool(self.config.get("use_reverse_proxy", False))
            self.reverse_proxy = self.config.get("reverse_proxy", "") or ""
            # refresh_interval 的单位是分钟，SubscriptionCenter 需要秒
            self.refresh_interval = max(1, _as_int(self.config.get("refresh_interval", 90), 90))
            self.easter_egg = _as_bool(self.config.get("easter_egg", False))
            self.easter_egg_list = self.config.get("easter_egg_list") or []
            self.enable_subscription = _as_bool(self.config.get("enable_subscription", False))
            # 注意：schema 里的键名是 max_update_limit，不是 update_limit
            self.max_update_limit = max(1, _as_int(self.config.get("max_update_limit", 10), 10))

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
            if self.enable_subscription:
                self.sub_center.set_callback(self._handle_sub_update)
                self.sub_center.start_timer()
            logger.info(f"Pid2Pdf插件初始化完成，临时目录: {self.temp_dir}")
            
        except Exception as e:
            logger.error(f"Pid2Pdf插件初始化失败: {e}", exc_info=True)

    @filter.command("pid2pdf")
    async def pid_to_pdf(self, event: AstrMessageEvent):
        """根据Pixiv ID下载图片并生成PDF"""
        # 解析用户输入的PID（也接受 Pixiv 作品链接）
        message_parts = event.message_str.strip().split()
        if len(message_parts) < 2:
            yield event.plain_result("请提供Pixiv ID，格式: /pid2pdf <PID>")
            return
        pid = _parse_pid_arg(message_parts[1])
        if not pid:
            yield event.plain_result(
                "Pixiv ID必须是数字，也可以直接把 Pixiv 作品链接发出来"
            )
            return
        async for result in self._send_artwork_pdf(event, pid):
            yield result

    async def _send_artwork_pdf(self, event: AstrMessageEvent, pid: str):
        """获取作品并发送完整版 PDF（命中缓存则直接发缓存）"""
        try:
            # 只有完整版才会存成 pixiv_<pid>.pdf，预览版另带 _preview 后缀，
            # 所以这里命中缓存就一定是完整的
            pdf_path = self.persistent_dir / f"pixiv_{pid}.pdf"
            if pdf_path.exists():
                # logger.info(f"本地已存在该PID的PDF文件: {pdf_path}")
                # 命中缓存也要先把作品信息发出来，取不到信息就只发文件
                artwork_info = await self._get_artwork_info(pid)
                if artwork_info:
                    yield event.plain_result(
                        _format_artwork_info(
                            artwork_info, include_tags=True, include_r18=True
                        )
                    )
                else:
                    yield event.plain_result(f"#PID: {pid}\n（本次使用本地缓存）")
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

            # 发送作品信息
            pid = str(artwork_info["id"])
            yield event.plain_result(
                _format_artwork_info(artwork_info, include_tags=True, include_r18=True)
            )

            # 生成PDF。万一没下全（个别图失败），也按预览命名，
            # 免得半份 PDF 被当成完整缓存
            preview = _is_partial(artwork_info, image_paths)
            if preview:
                logger.warning(
                    f"PID {pid} 只拿到 {len(image_paths)}/{_total_pages(artwork_info)} 张，"
                    f"按预览版命名"
                )
            pdf_path = await self._create_pdf(image_paths, pid, preview=preview)
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
        # 解析用户输入的PID（也接受 Pixiv 作品链接）
        message_parts = event.message_str.strip().split()
        if len(message_parts) < 2:
            yield event.plain_result("请提供Pixiv ID，格式: /pid <PID>")
            return
        pid = _parse_pid_arg(message_parts[1])
        if not pid:
            yield event.plain_result(
                "Pixiv ID必须是数字，也可以直接把 Pixiv 作品链接发出来"
            )
            return
        async for result in self._send_artwork_images(event, pid):
            yield result

    async def _send_artwork_images(self, event: AstrMessageEvent, pid: str):
        """获取作品并直接发送图片。也供 Pixiv 链接识别复用。"""
        try:
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

            # 发送作品信息（含标签）
            pid = str(artwork_info["id"])
            yield event.plain_result(
                _format_artwork_info(artwork_info, include_tags=True, include_r18=True)
            )
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
            error_info = ''
            for i in range(3):
                try:
                    result = self.papi.illust_detail(pid)
                except Exception as e:
                    logger.error(f"获取作品详情失败: {e}")
                    error_info = e
                    result = None
                if result and result.illust:
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
                        "sanity_level": artwork.sanity_level,
                        "tags": artwork.tags,
                        # /pid 和 /pid2pdf 的信息里也要能显示 AI 标记
                        "is_ai": _is_ai_illust(artwork)
                    }
                else:
                    logger.info("尝试重新登录Pixiv")
                    self.papi.auth(refresh_token=self.refresh_token)
                    await asyncio.sleep(1)
        except Exception as e:
            logger.error(f"获取作品信息失败: {e}")
        logger.info(f"未找到PID {pid} 的作品,错误信息{error_info}")
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
            # logger.info(f"下载了 {len(image_paths)} 张图片")
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
                        # # Determine file extension from content type
                        # content_type = response.headers.get('content-type', '')
                        # if 'jpeg' in content_type or 'jpg' in content_type:
                        #     file_extension = 'jpg'
                        # elif 'png' in content_type:
                        #     file_extension = 'png'
                        # elif 'gif' in content_type:
                        #     file_extension = 'gif'
                        # else:
                        #     # Get extension from URL
                        #     file_extension = url.split('.')[-1].split('?')[0]
                        #     if file_extension not in ['jpg', 'jpeg', 'png', 'gif']:
                        #         file_extension = 'jpg'  # Default to jpg
                        
                        # file_path = self.temp_dir / f"{pid}/image_{index}.{file_extension}"
                        file_path = self.temp_dir / f"{pid}/image_{index}.jpg"
                        
                        img_data = await response.read()
                        if modify_hash:
                            img_data = await asyncio.to_thread(_image_obfus, img_data)
                        async with aiofiles.open(file_path, 'wb') as f:
                            await f.write(img_data)
                        
                        # logger.info(f"下载图片 {index}: {file_path}")
                        return file_path
                    else:
                        logger.error(f"下载图片失败，状态码: {response.status}")
                        return None
            
        except Exception as e:
            logger.error(f"下载单张图片失败: {e}")
            return None

    async def _create_pdf(self, image_paths: List[Path], pdf_name: str, preview: bool = False) -> Path:
        """将图片转换为PDF

        preview=True 表示这只是部分页数的预览版，文件名会带 _preview 后缀，
        这样 /pid2pdf 的完整版缓存不会误命中一个只有前 10 张的 PDF。
        """
        try:
            if not image_paths:
                return None
            suffix = "_preview" if preview else ""
            pdf_path = self.persistent_dir / f"pixiv_{pdf_name}{suffix}.pdf"

            # img2pdf.convert 和写盘都是同步阻塞操作，多图作品会卡住整个
            # AstrBot 事件循环，这里丢到线程里执行。
            def _write_pdf() -> None:
                with open(pdf_path, 'wb') as f:
                    f.write(img2pdf.convert(image_paths))

            await asyncio.to_thread(_write_pdf)
            # logger.info(f"生成PDF: {pdf_path}")
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
                # logger.info(f"PDF文件已生成并发送: {pid}.pdf")
            else:
                yield event.plain_result("PDF文发送失败")
            
        except Exception as e:
            logger.error(f"发送PDF失败: {e}")
            yield event.plain_result(f"发送PDF文件失败: {str(e)}")

    async def _send_img(self, event: AstrMessageEvent, img_path: Path, pid: str, fake_record = False):
        """发送图片文件给用户"""
        try:
            # 排序后再发送，否则 image_10 会排在 image_2 前面
            imgs = _sorted_images(img_path)
            if not imgs:
                yield event.plain_result("图片发送失败")
                return

            # 每条消息链最多 10 个组件，超出就分页发送
            chains: List[list] = []
            chain: list = [Plain(f'PID：{pid}')]
            for img in imgs:
                if len(chain) >= 10:
                    chains.append(chain)
                    chain = []
                chain.append(Image.fromFileSystem(str(img.absolute())))
            if chain:
                chains.append(chain)

            if fake_record:
                for one_chain in chains:
                    node = Node(
                            uin=event.get_self_id(),
                            name="AstrBot",
                            content=one_chain
                        )
                    yield event.chain_result([node])
            else:
                for one_chain in chains:
                    yield event.chain_result(one_chain)
            # logger.info(f"图片已送: {pid}")
            yield event.plain_result("图片已发送，如果看不到，就是被企鹅的大手截胡了，改用/pid2pdf发送吧！")
            
        except Exception as e:
            logger.error(f"发送图片失败: {e}")
            yield event.plain_result(f"发送图片失败: {str(e)}")


    async def _cleanup_temp_files(self):
        """清理临时文件

        清理策略尚未实现（见 README 计划功能）。这里刻意保留 temp/ 缓存，
        因为 _download_single_image 会靠它跳过重复下载。
        """
        try:
            if self.temp_dir and self.temp_dir.exists():
                # TODO: 按策略（大小/时间）清理，目前只保留缓存
                logger.debug("临时文件清理策略尚未实现，保留 temp/ 缓存")
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
            date = None  # 默认当前日期
            count = 5  # 默认获取5个作品
            
            # 解析参数
            if len(message_parts) >= 2:
                # 第一个参数是排行榜类型
                mode_input = message_parts[1].lower()
                if mode_input in RANKING_MODES:
                    mode = mode_input
                elif mode_input.isdigit():
                    count = max(1, min(int(mode_input), 10))  # 最多10个作品
            
            if len(message_parts) >= 3:
                # 第二个参数可能是数量
                if message_parts[2].isdigit():
                    count = max(1, min(int(message_parts[2]), 10))

            # 应用R18过滤设置：只有 R18 榜才需要被降级，
            # 以前的写法会把 day_male / week_rookie 这类正常榜单也改写成日榜。
            r18_mode = self.config.get("r18_mode", "过滤 R18")
            if r18_mode == "过滤 R18" and mode in R18_RANKING_MODES:
                mode = "day"  # 强制使用日榜

            # 注意：_process_ranking_request 是异步生成器，必须用 async for，
            # 用普通 for 会抛 TypeError: 'async_generator' object is not iterable
            async for result in self._process_ranking_request(event, mode, date, count):
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
            error_info = ''
            for i in range(3):
                try:
                    result = self.papi.illust_ranking(mode=mode, date=date)
                except Exception as e:
                    logger.error(f"获取排行榜数据失败: {e}")
                    error_info = e
                    result = None
                if result and result.illusts:
                    break
                else:
                    logger.info("尝试重新登录Pixiv")
                    self.papi.auth(refresh_token=self.refresh_token)
                    await asyncio.sleep(1)
            if result and result.illusts:
                # 应用AI过滤设置
                ai_filter_mode = self.config.get("ai_filter_mode", "显示 AI 作品")
                filtered_illusts = []
                
                for illust in result.illusts[:count * 2]:  # 获取更多以便过滤
                    # AI作品过滤
                    is_ai = _is_ai_illust(illust)
                    
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
                        "tags": illust.tags,
                        "is_ai": is_ai
                    })
                    
                    if len(filtered_illusts) >= count:
                        break
                
                return filtered_illusts[:count]
            else:
                logger.error(f"排行榜数据为空,错误信息：{error_info}")
                return None
                
        except Exception as e:
            logger.error(f"获取排行榜数据失败: {e}")
            return None
    
    async def _send_ranking_results(self, event: AstrMessageEvent, ranking_data: list, count: int, mode: str):
        """发送排行榜结果"""
        try:
            pdf_img_paths = []
            combined_infos = ["作品信息：\n"]
            is_r18 = mode in R18_RANKING_MODES
            for i, artwork in enumerate(ranking_data, 1):
                pid = str(artwork["id"])
                is_r18 = mode in R18_RANKING_MODES
                # 构建作品信息
                info_text = _format_artwork_info(artwork, index=i)
                if is_r18:
                    combined_infos.append(info_text + "\n\n")
                else:
                    yield event.plain_result(info_text)
                
                # 下载并发送第一张图片作为预览
                try:
                    # 检查本地是否已有图片
                    img_dir = self.temp_dir / f"{pid}"
                    existing_imgs = _sorted_images(img_dir)
                    if existing_imgs:
                        # 发送已有的第一页（排序过，image_0 才是第一页）
                        first_img = existing_imgs[0]
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
                # 排行榜每个作品只取第一张，天然是预览集合，按预览命名
                pdf_path = await self._create_pdf(pdf_img_paths, pdf_name, preview=True)
                if not pdf_path:
                    yield event.plain_result(f"生成PDF失败")
                    return
                yield event.chain_result([File(file=str(pdf_path),name=pdf_path.name)])
                chain = []
                for info in combined_infos:
                    chain.append(Plain(info))
                node = Node(
                            uin=event.get_self_id(),
                            name="AstrBot",
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
            error_info = None
            # 必须先初始化：三次都失败时 user_detail 不能处于未绑定状态，
            # 否则下面的 `if not user_detail` 会抛 UnboundLocalError
            user_detail = None
            for i in range(3):
                try:
                    user_detail = self.papi.user_detail(uid)
                except Exception as e:
                    logger.error(f"获取画师信息失败: {e}")
                    error_info = e
                    user_detail = None
                if user_detail and user_detail.user:
                    break
                logger.info("尝试重新登录Pixiv")
                self.papi.auth(refresh_token=self.refresh_token)
                await asyncio.sleep(1)
            if not user_detail or not user_detail.user:
                logger.error(f"未找到画师 {uid}，错误信息：{error_info}")
                return None
            
            artist_name = user_detail.user.name
            # logger.info(f"找到画师: {artist_name} (UID: {uid})")
            
            # 获取画师的插画作品
            result = None
            for i in range(3):
                try:
                    result = self.papi.user_illusts(uid)
                except Exception as e:
                    logger.error(f"获取画师作品列表失败: {e}")
                    result = None
                if result and result.illusts is not None:
                    break
                logger.info("尝试重新登录Pixiv")
                self.papi.auth(refresh_token=self.refresh_token)
                await asyncio.sleep(1)
            if not result or not result.illusts:
                logger.error(f"画师 {uid} 没有作品")
                return None
            
            # 应用过滤设置
            r18_mode = self.config.get("r18_mode", "过滤 R18")
            ai_filter_mode = self.config.get("ai_filter_mode", "显示 AI 作品")
            
            filtered_works = []
            for illust in result.illusts:
                # R18过滤
                is_r18_r18g = _is_r18_artwork(illust.tags)
                if r18_mode == "过滤 R18" and is_r18_r18g:
                    continue
                elif r18_mode == "仅 R18" and not is_r18_r18g:
                    continue
                
                # AI作品过滤
                is_ai = _is_ai_illust(illust)
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
                    "tags": illust.tags,
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

    async def _get_artist_mangas(self, uid: str, count: int = 5) -> list:
        """获取画师的最新漫画"""
        try:
            if not self.papi:
                logger.error("Pixiv API未初始化")
                return None
            
            # 获取画师信息
            error_info = None
            user_detail = None
            for i in range(3):
                try:
                    user_detail = self.papi.user_detail(uid)
                except Exception as e:
                    logger.error(f"获取画师信息失败: {e}")
                    error_info = e
                    user_detail = None
                if user_detail and user_detail.user:
                    break
                logger.info("尝试重新登录Pixiv")
                self.papi.auth(refresh_token=self.refresh_token)
                await asyncio.sleep(1)
            if not user_detail or not user_detail.user:
                logger.error(f"未找到画师 {uid}，错误信息：{error_info}")
                return None
            
            artist_name = user_detail.user.name
            # logger.info(f"找到画师: {artist_name} (UID: {uid})")
            
            # 获取画师的插画作品
            result = None
            for i in range(3):
                try:
                    result = self.papi.user_illusts(uid, "manga")
                except Exception as e:
                    logger.error(f"获取画师漫画列表失败: {e}")
                    result = None
                if result and result.illusts is not None:
                    break
                logger.info("尝试重新登录Pixiv")
                self.papi.auth(refresh_token=self.refresh_token)
                await asyncio.sleep(1)
            if not result or not result.illusts:
                logger.error(f"画师 {uid} 没有作品")
                return None
            
            # 应用过滤设置
            r18_mode = self.config.get("r18_mode", "过滤 R18")
            ai_filter_mode = self.config.get("ai_filter_mode", "显示 AI 作品")
            
            filtered_works = []
            for illust in result.illusts:
                # R18过滤
                is_r18_r18g = _is_r18_artwork(illust.tags)
                if r18_mode == "过滤 R18" and is_r18_r18g:
                    continue
                elif r18_mode == "仅 R18" and not is_r18_r18g:
                    continue
                
                # AI作品过滤
                is_ai = _is_ai_illust(illust)
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
                    "tags": illust.tags,
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
                is_ai = artwork.get("is_ai", False)
                # 构建作品信息
                info_text = f"#{i} PID: {pid}\n"
                info_text += f"标题: {title}\n"
                pages = artwork.get("meta_pages")
                is_r18_r18g = _is_r18_artwork(artwork["tags"])
                if pages:
                    info_text += f"多图作品，共{len(pages)}张"
                if is_ai:
                    info_text += " | AI作品"
                
                yield event.plain_result(info_text)
                
                # 下载并发送第一张图片作为预览
                try:
                    # 检查本地是否已有图片
                    img_dir = self.temp_dir / f"{pid}"
                    existing_imgs = _sorted_images(img_dir)
                    if existing_imgs:
                        # 发送已有的第一页（排序过，image_0 才是第一页）
                        first_img = existing_imgs[0]
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

        uid = _parse_uid_arg(message_parts[1])
        if not uid:
            yield event.plain_result(
                "画师UID必须是数字，也可以直接把 Pixiv 画师链接发出来"
            )
            return
        async for result in self._subscribe_artist(event, uid):
            yield result

    async def _subscribe_artist(self, event: AstrMessageEvent, uid: str):
        """订阅画师，并立刻拉一次最新作品发出来。

        也供 Pixiv 画师链接识别复用。
        """
        if not self.enable_subscription or self.sub_center is None:
            yield event.plain_result("订阅功能未开启")
            return
        if not uid.isdigit():
            yield event.plain_result("画师UID必须是数字")
            return

        group_id = event.unified_msg_origin
        # 添加订阅
        await self.sub_center.add_subscription(uid, group_id)
        yield event.plain_result(
            f"成功订阅画师 UID: {uid} 的最新作品，使用命令「刷新订阅」可立即获取最新作品"
        )

        # 订阅成功后立刻按 /puid 的方式拉一次，并把这次已经发过的最新作品 ID
        # 写进订阅记录，免得下一轮定时刷新把刚发过的作品重复发一遍
        artist_works = await self._get_artist_works(uid, 5)
        if not artist_works:
            yield event.plain_result(f"暂时无法获取画师 {uid} 的作品，之后会自动刷新")
            return

        artist_name = artist_works.get("artist_name")
        works = artist_works.get("works") or []
        if not works:
            yield event.plain_result(
                f"画师 {artist_name} (UID: {uid}) 没有符合过滤条件的作品"
            )
            return

        yield event.plain_result(
            f"画师: {artist_name} (UID: {uid})\n共找到 {len(works)} 个作品"
        )
        async for result in self._send_artist_works(event, artist_works, uid, len(works)):
            yield result

        newest_id = max(int(work["id"]) for work in works)
        await self.sub_center.renew_last_updated_id(uid, newest_id)
        await self.sub_center.renew_last_updated_time(uid)
        logger.info(f"订阅画师 {uid} 完成，最新作品ID已记录为 {newest_id}")

    @filter.command("删除订阅")
    async def remove_sub(self, event: AstrMessageEvent):
        """删除订阅"""
        if not self.enable_subscription or self.sub_center is None:
            yield event.plain_result("订阅功能未开启")
            return
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

    @filter.command("刷新订阅")
    async def refresh_subscriptions(self, event: AstrMessageEvent):
        """手动触发一次订阅刷新"""
        if not self.enable_subscription or self.sub_center is None:
            yield event.plain_result("订阅功能未开启")
            return
        yield event.plain_result("开始手动刷新订阅，请稍候…")
        await self.sub_center.manual_refresh()

    async def _handle_sub_update(self, sub_data_list: list[SubscriptionData]):
        logger.info("开始更新订阅")
        try:
            update_count = 0
            for sub_data in sub_data_list:
                if update_count >= self.max_update_limit:
                    logger.info(f"本次更新已达到最大限制 {self.max_update_limit}，跳过剩余画师")
                    break
                user_id = sub_data["user_id"]
                sub_groups = sub_data["sub_groups"]
                last_updated_id = sub_data["last_updated_id"]
                new_updated_id = int(last_updated_id)
                last_updated_time = sub_data["last_updated_time"]
                rand_update_interval =random.randint(86400, 172800)
                if int(datetime.now().timestamp()) - int(last_updated_time) < rand_update_interval:
                    # logger.info(f"画师 {user_id} 的上次作品更新距离现在不足{rand_update_interval//3600}小时，跳过本次更新")
                    continue
                await asyncio.sleep(10)
                # 获取最新插图和漫画
                for content_type in ["插画", "漫画"]:
                    artist_works = None
                    if content_type == "插画":
                        artist_works = await self._get_artist_works(user_id, 10)
                    else:
                        continue
                        artist_works = await self._get_artist_mangas(user_id, 1)
                    if not artist_works:
                        logger.error(f"无法获取画师 {user_id} 的 {content_type} 作品信息")
                        continue
                    await self.sub_center.renew_last_updated_time(user_id)
                    artist_name = artist_works["artist_name"]
                    works = artist_works["works"] or []
                    works.sort(key=lambda x: int(x["id"]), reverse=True)
                    new_works = []
                    #单一类型的最新作品id
                    _new_updated_id_single_type = int(last_updated_id)
                    for artwork_info in works:
                        _new_updated_id_single_type = max(_new_updated_id_single_type, int(artwork_info["id"]))
                        if int(artwork_info["id"]) <= int(last_updated_id):
                            break
                        new_works.append(artwork_info)
                    new_works = new_works[:5]
                    # 更新最后作品ID
                    if _new_updated_id_single_type > new_updated_id:
                        new_updated_id = _new_updated_id_single_type
                        await self.sub_center.renew_last_updated_id(user_id, new_updated_id)
                    if len(new_works) == 0:
                        # logger.info(f"画师 {artist_name} (UID: {user_id}) 没有符合过滤条件的 {content_type} 新作品")
                        continue
                    else:
                        update_count += 1
                    for group_id in sub_groups:
                        await self.context.send_message(group_id, MessageChain().message(f"画师: {artist_name} (UID: {user_id})\n有 {len(new_works)} 个{content_type}新作品"))
                    for artwork_info in new_works:
                        await asyncio.sleep(3)
                        #发送作品信息
                        pid = str(artwork_info["id"])
                        is_r18_r18g = _is_r18_artwork(artwork_info.get("tags"))
                        info_text = _format_artwork_info(
                            artwork_info, include_tags=True, include_r18=True
                        )
                        for group_id in sub_groups:
                            await self.context.send_message(group_id, MessageChain().message(info_text))

                        # 下载图片（订阅只下前 10 张做预览）
                        image_paths = await self._download_images(artwork_info, pid, 10)
                        if not image_paths:
                            logger.info(f"下载PID {pid} 的图片失败")
                        else:
                            img_msg_chain = MessageChain()
                            if is_r18_r18g:
                                # 生成PDF。订阅最多只下 10 张，没下全就按预览命名，
                                # 免得 /pid2pdf 把它当成完整缓存直接发出去
                                preview = _is_partial(artwork_info, image_paths)
                                pdf_path = await self._create_pdf(
                                    image_paths, pid, preview=preview
                                )
                                if not pdf_path:
                                    img_msg_chain = img_msg_chain.message("生成pdf失败")
                                else:
                                    img_msg_chain.chain = [
                                        File(
                                            file=str(pdf_path.absolute()),
                                            name=pdf_path.name,
                                        )
                                    ]
                            else:
                                for img in image_paths:
                                    img_msg_chain = img_msg_chain.file_image(str(img.absolute()))
                            for group_id in sub_groups:
                                try:
                                    await self.context.send_message(group_id, img_msg_chain)
                                except Exception as e:
                                    logger.error(f"发送订阅图片失败，{e}")
        except Exception as e:
            logger.error(f"更新订阅时出错： {e}")



    @filter.event_message_type(filter.EventMessageType.GROUP_MESSAGE)
    async def handle_text_event(self, event: AstrMessageEvent):
        """简易命令 + Pixiv 链接识别

        简易命令：今日色图 今日ai色图 今日排行榜 今日ai图
        链接识别：作品链接走 /pid，画师链接走 /订阅画师
        """
        text = event.message_str.strip()

        # 0) 指令消息交给指令处理器，避免 /pid <链接> 这类写法重复触发
        if _looks_like_plugin_command(text):
            return

        # 1) 简易命令
        if text in SIMPLE_COMMAND_MODES:
            async for result in self._process_ranking_request(
                event, mode=SIMPLE_COMMAND_MODES[text], date=None, count=10
            ):
                yield result
            return

        # 2) Pixiv 作品链接 -> 走 /pid
        pid = _extract_pixiv_artwork_id(text)
        if pid:
            logger.info(f"识别到 Pixiv 作品链接，PID: {pid}")
            async for result in self._send_artwork_images(event, pid):
                yield result
            return

        # 3) Pixiv 画师链接 -> 走订阅画师
        uid = _extract_pixiv_user_id(text)
        if uid:
            logger.info(f"识别到 Pixiv 画师链接，UID: {uid}")
            async for result in self._subscribe_artist(event, uid):
                yield result
            return

        # 4) 彩蛋 随机排行榜 超过一天后可再次触发，几率10%
        if (
            self.easter_egg
            and self.easter_egg_list  # 空列表会让 random.choice 抛异常
            and int(datetime.now().timestamp()) - self.egg_trigger_time > 86400
            and random.random() < 0.1
        ):
            self.egg_trigger_time = int(datetime.now().timestamp())
            async with aiofiles.open(str(self.egg_trigger_record_file), "w") as f:
                await f.write(str(self.egg_trigger_time))
            rank_name = random.choice(self.easter_egg_list)
            yield event.plain_result(f"你触发了今天的彩蛋！即将发送：{rank_name}")
            if rank_name in SIMPLE_COMMAND_MODES:
                async for result in self._process_ranking_request(
                    event, mode=SIMPLE_COMMAND_MODES[rank_name], date=None, count=10
                ):
                    yield result


    
    @filter.command("pid_help")
    async def help_command(self, event: AstrMessageEvent):
        """显示插件帮助信息"""
        mode_lines = "\n".join(
            f"- {mode}: {label}" for mode, label in RANKING_MODE_LABELS.items()
        )
        help_text = f"""
Pid2Pdf 插件使用说明：

命令格式：
/pid2pdf <Pixiv_ID> - 根据Pixiv ID下载图片并生成PDF
/pid <Pixiv_ID> - 根据Pixiv ID下载图片并发送
/pixiv_ranking [类型] [数量] - 获取Pixiv排行榜作品
/puid <UID> [数量] - 根据画师UID下载最新作品
/订阅画师 <UID> - 订阅画师的最新作品（订阅后立刻拉一次最新作品）
/删除订阅 <UID> - 取消订阅
/刷新订阅 - 立即刷新一次订阅
/pid_config - 查看当前配置状态

排行榜类型：
{mode_lines}

简易命令（群里直接发这几个词即可）：
今日色图 / 今日ai色图 / 今日排行榜 / 今日ai图

链接识别（群里直接发链接即可）：
https://www.pixiv.net/artworks/123456789  -> 等同于 /pid 123456789
https://www.pixiv.net/users/12345678      -> 等同于 /订阅画师 12345678

另外 /pid、/pid2pdf、/订阅画师 的参数也可以直接填链接。

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
订阅功能: {'已启用' if self.enable_subscription else '未启用'}
R18 过滤: {self.config.get('r18_mode', '过滤 R18')}
AI 作品过滤: {self.config.get('ai_filter_mode', '显示 AI 作品')}

如需配置，请在插件配置文件中设置：
- refresh_token: 您的Pixiv refresh_token
- proxy: 代理服务器地址（可选）
        """
        yield event.plain_result(config_info.strip())

    async def terminate(self):
        """插件销毁方法"""
        await self._cleanup_temp_files()
        # initialize() 可能中途失败导致 sub_center 未创建，这里不能无条件访问
        if self.sub_center is not None:
            await self.sub_center.cleanup()
        logger.info("Pid2Pdf插件已销毁")

def _image_obfus(img_data):
    """破坏图片哈希（同步 CPU 操作，调用方需用 asyncio.to_thread 包一层）"""
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
                    img.save(output, format="JPEG", quality=95, subsampling=0)
                    return output.getvalue()

    except Exception as e:
        logger.warning(f"破坏图片哈希时发生错误: {str(e)}")
        return img_data
    