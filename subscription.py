import asyncio
import json
from astrbot.api import logger
from typing import Callable, Any, Optional, TypedDict, List
from pathlib import Path
import aiofiles
from datetime import datetime


class SubscriptionData(TypedDict):
    """
    订阅数据类，包含订阅对象ID和最后更新的作品id
    """

    user_id: str
    last_updated_id: str
    sub_groups: List[str]


class SubscriptionCenter:
    """
    订阅中心类，用于管理订阅对象和定时刷新
    """

    def __init__(
        self,
        storage_file: str = "subscriptions.json",
        refresh_interval: int = 3600 * 5,
        max_update_count: int = 5,
    ) -> None:
        """
        初始化订阅中心

        Args:
            storage_file: 订阅数据存储文件路径
            refresh_interval: 定时刷新间隔（秒）
        """
        self.storage_file = Path(storage_file)
        self.max_update_count = max_update_count
        self.refresh_interval = refresh_interval
        self.subscriptions: List[SubscriptionData] = []
        self.callback: Optional[Callable[[List[SubscriptionData]], Any]] = None
        self._timer_task: Optional[asyncio.Task] = None
        self._is_running = False
        self._lock = asyncio.Lock()

    async def initilize(self):
        await self._load_subscriptions()

    async def _load_subscriptions(self) -> None:
        """
        从本地文件加载订阅数据
        """
        try:
            if self.storage_file.exists():
                async with aiofiles.open(self.storage_file, "r", encoding="utf-8") as f:
                    content = await f.read()
                    if content.strip():
                        data = json.loads(content)
                        self.subscriptions = data.get("subscriptions", [])
                        logger.info(f"成功加载 {len(self.subscriptions)} 个订阅对象")
            else:
                logger.info("订阅存储文件不存在，将创建新文件")
        except json.JSONDecodeError as e:
            logger.error(f"订阅数据文件格式错误: {e}")
        except Exception as e:
            logger.error(f"加载订阅数据失败: {e}")

    async def _save_subscriptions(self) -> None:
        """
        保存订阅数据到本地文件
        """
        try:
            data = {
                "subscriptions": self.subscriptions,
                "last_updated": datetime.now().isoformat(),
            }
            async with aiofiles.open(self.storage_file, "w", encoding="utf-8") as f:
                await f.write(json.dumps(data, indent=2, ensure_ascii=False))
            logger.debug("订阅数据已保存")
        except Exception as e:
            logger.error(f"保存订阅数据失败: {e}")

    async def add_subscription(self, sub_id: int, group_id: str) -> bool:
        """
        增加订阅
        Args:
            sub_id: 订阅对象ID
            group_id: 订阅群组

        Returns:
            bool: 操作是否成功
        """
        try:
            async with self._lock:
                is_new_sub = True
                for sub_data in self.subscriptions:
                    if sub_data["user_id"] == sub_id:
                        if group_id not in sub_data["sub_groups"]:
                            sub_data["sub_groups"].append(group_id)
                        is_new_sub = False
                        break
                if is_new_sub:
                    self.subscriptions.append(
                        SubscriptionData(
                            user_id=sub_id, last_updated_id=0, sub_groups=[group_id]
                        )
                    )
                logger.info(f"成功添加订阅对象: {sub_id}，群组：{group_id}")
                await self._save_subscriptions()
            return True
        except Exception as e:
            logger.error(f"添加订阅失败: {e}")
            return False

    async def remove_subscription(self, sub_id: int, group_id: str) -> bool:
        """
        删除订阅

        Args:
            sub_id: 订阅对象ID
            group_id: 订阅群组

        Returns:
            bool: 操作是否成功
        """
        try:
            async with self._lock:
                for sub_data in self.subscriptions:
                    if sub_data["user_id"] == sub_id:
                        if group_id in sub_data["sub_groups"]:
                            sub_data["sub_groups"].remove(group_id)
                        if len(sub_data["sub_groups"]) == 0:
                            self.subscriptions.remove(sub_data)
                        break
                logger.info(f"成功删除订阅")
                await self._save_subscriptions()
            return True
        except Exception as e:
            logger.error(f"删除订阅失败: {e}")
            return False

    def set_callback(self, callback: Callable[[List[SubscriptionData]], Any]) -> None:
        """
        设置刷新回调函数

        Args:
            callback: 回调函数，接收订阅对象集合作为参数
        """
        self.callback = callback
        logger.info("回调函数设置成功")

    async def _refresh_task(self) -> None:
        """
        定时刷新任务
        """
        while self._is_running:
            try:
                await asyncio.sleep(self.refresh_interval)
                await self._trigger_refresh()
            except asyncio.CancelledError:
                logger.info("定时刷新任务被取消")
                break
            except Exception as e:
                logger.error(f"定时刷新任务执行异常: {e}")
                await asyncio.sleep(self.refresh_interval)

    async def _trigger_refresh(self) -> None:
        """
        触发刷新回调
        """
        if not self.callback:
            logger.warning("未设置回调函数，跳过刷新")
            return

        if not self.subscriptions:
            logger.info("暂无订阅对象，跳过刷新")
            return

        try:
            # 创建订阅集合的副本，避免在回调执行期间被修改
            subscriptions_copy = self.subscriptions.copy()
            # 执行回调函数
            if asyncio.iscoroutinefunction(self.callback):
                await self.callback(subscriptions_copy)
            else:
                # 如果回调函数是同步的，在线程池中执行以避免阻塞
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(None, self.callback, subscriptions_copy)

            logger.info("订阅刷新完成")
        except Exception as e:
            logger.error(f"刷新回调执行失败: {e}")

    def start_timer(self) -> bool:
        """
        开始定时器

        Returns:
            bool: 操作是否成功
        """
        if self._is_running:
            logger.warning("定时器已在运行中")
            return False

        if not self.callback:
            logger.error("未设置回调函数，无法启动定时器")
            return False

        try:
            self._is_running = True
            self._timer_task = asyncio.create_task(self._refresh_task())
            logger.info(f"定时器已启动，刷新间隔: {self.refresh_interval}秒")
            return True
        except Exception as e:
            logger.error(f"启动定时器失败: {e}")
            return False

    async def stop_timer(self) -> bool:
        """
        关闭定时器

        Returns:
            bool: 操作是否成功
        """
        if not self._is_running:
            logger.warning("定时器未运行")
            return False

        try:
            self._is_running = False
            if self._timer_task and not self._timer_task.done():
                self._timer_task.cancel()
                try:
                    await self._timer_task
                except asyncio.CancelledError:
                    pass

            logger.info("定时器已停止")
            return True
        except Exception as e:
            logger.error(f"停止定时器失败: {e}")
            return False

    async def manual_refresh(self) -> bool:
        """
        手动触发一次刷新

        Returns:
            bool: 操作是否成功
        """
        try:
            logger.info("手动触发订阅刷新")
            await self._trigger_refresh()
            return True
        except Exception as e:
            logger.error(f"手动刷新失败: {e}")
            return False

    async def renew_last_updated_id(self, sub_id: int, new_last_id: int) -> bool:
        """
        更新订阅对象的最后更新作品ID

        Args:
            sub_id: 订阅对象ID
            new_last_id: 新的最后更新作品ID

        Returns:
            bool: 操作是否成功
        """
        try:
            async with self._lock:
                for sub_data in self.subscriptions:
                    if sub_data["user_id"] == sub_id:
                        sub_data["last_updated_id"] = str(new_last_id)
                        logger.info(f"成功更新订阅对象 {sub_id} 的最后更新作品ID为 {new_last_id}")
                        await self._save_subscriptions()
                        return True
            logger.warning(f"未找到订阅对象 {sub_id}，无法更新最后更新作品ID")
            return False
        except Exception as e:
            logger.error(f"更新最后更新作品ID失败: {e}")
            return False
        
    async def cleanup(self) -> None:
        """
        清理资源
        """
        await self.stop_timer()
