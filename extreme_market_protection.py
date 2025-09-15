#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
极端行情防护机制
当单边趋势超过10%阈值时，触发紧急双向全部平仓，网格进入24小时休眠状态

功能:
1. 实时监控单边趋势幅度
2. 10%阈值触发紧急平仓
3. 24小时休眠机制
4. ATR恢复正常后重启网格
5. 多重安全检查和日志记录
"""

import asyncio
import time
import logging
import json
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
from dataclasses import dataclass
from config import config

logger = logging.getLogger(__name__)

@dataclass
class KlineData:
    """1小时K线数据类"""
    timestamp: datetime
    open_price: float
    high_price: float
    low_price: float
    close_price: float
    volume: float
    direction: str  # 'up', 'down', 'neutral'
    change_percent: float  # 单根K线涨跌幅

@dataclass
class MarketState:
    """市场状态数据类"""
    timestamp: datetime
    price: float
    trend_start_price: float
    trend_start_time: datetime
    trend_direction: str  # 'up', 'down', 'neutral'
    trend_magnitude: float  # 连续同向K线累计涨跌幅百分比
    consecutive_klines: int  # 连续同向K线数量
    atr_value: float
    is_extreme: bool
    protection_triggered: bool

@dataclass
class ProtectionConfig:
    """防护配置"""
    extreme_threshold: float = 11.0  # 极端阈值 11%
    hibernation_hours: int = 24  # 休眠时间 24小时
    atr_recovery_multiplier: float = 1.5  # ATR恢复倍数
    trend_detection_window: int = 20  # 趋势检测窗口
    min_trend_duration: int = 3  # 最小趋势持续时间
    emergency_close_timeout: int = 30  # 紧急平仓超时时间(秒)

class ExtremeMarketProtection:
    """
    极端行情防护系统
    
    核心功能:
    1. 实时趋势监控
    2. 极端行情检测
    3. 紧急平仓执行
    4. 休眠状态管理
    5. 自动恢复机制
    """
    
    def __init__(self, config: ProtectionConfig = None):
        self.config = config or ProtectionConfig()
        
        # K线数据缓冲区
        self.kline_buffer: List[KlineData] = []
        self.max_kline_buffer_size = 168  # 保留7天的1小时K线数据
        
        # 市场数据缓冲区(保留用于ATR计算)
        self.price_buffer: List[Tuple[datetime, float]] = []
        self.max_buffer_size = 100
        
        # 连续同向K线趋势状态
        self.consecutive_trend_start_price = None
        self.consecutive_trend_start_time = None
        self.consecutive_trend_direction = 'neutral'
        self.consecutive_kline_count = 0
        self.cumulative_change_percent = 0.0
        
        # 原有趋势状态(保留用于兼容)
        self.current_trend_start_price = None
        self.current_trend_start_time = None
        self.current_trend_direction = 'neutral'
        self.trend_peaks_valleys = []  # 峰谷记录
        
        # 防护状态
        self.protection_active = False
        self.hibernation_start_time = None
        self.last_atr_values = []  # ATR历史值
        self.baseline_atr = None  # 基准ATR值
        
        # 状态文件路径
        self.state_file = "extreme_protection_state.json"
        
        # 初始化
        self._load_state()
        
        logger.info("极端行情防护系统初始化完成")
        logger.info(f"防护配置: 阈值={self.config.extreme_threshold}%, 休眠={self.config.hibernation_hours}小时")
    
    def _load_state(self):
        """加载防护状态"""
        try:
            with open(self.state_file, 'r', encoding='utf-8') as f:
                state = json.load(f)
                
            self.protection_active = state.get('protection_active', False)
            hibernation_start = state.get('hibernation_start_time')
            if hibernation_start:
                self.hibernation_start_time = datetime.fromisoformat(hibernation_start)
            
            self.baseline_atr = state.get('baseline_atr')
            
            # 加载连续趋势状态
            self.consecutive_trend_direction = state.get('consecutive_trend_direction', 'neutral')
            self.consecutive_kline_count = state.get('consecutive_kline_count', 0)
            self.cumulative_change_percent = state.get('cumulative_change_percent', 0.0)
            
            if state.get('consecutive_trend_start_time'):
                self.consecutive_trend_start_time = datetime.fromisoformat(state['consecutive_trend_start_time'])
            self.consecutive_trend_start_price = state.get('consecutive_trend_start_price')
            
            logger.info(f"已加载防护状态: 激活={self.protection_active}, 休眠开始={self.hibernation_start_time}, "
                      f"连续趋势={self.consecutive_trend_direction}, K线数={self.consecutive_kline_count}")
            
        except FileNotFoundError:
            logger.info("未找到状态文件，使用默认状态")
        except Exception as e:
            logger.error(f"加载状态文件失败: {e}")
    
    def _save_state(self):
        """保存保护状态"""
        try:
            state = {
                'protection_active': self.protection_active,
                'hibernation_start_time': self.hibernation_start_time.isoformat() if self.hibernation_start_time else None,
                'baseline_atr': self.baseline_atr,
                'consecutive_trend_direction': self.consecutive_trend_direction,
                'consecutive_kline_count': self.consecutive_kline_count,
                'cumulative_change_percent': self.cumulative_change_percent,
                'consecutive_trend_start_time': self.consecutive_trend_start_time.isoformat() if self.consecutive_trend_start_time else None,
                'consecutive_trend_start_price': self.consecutive_trend_start_price,
                'last_update': datetime.now().isoformat()
            }
            
            with open(self.state_file, 'w', encoding='utf-8') as f:
                json.dump(state, f, indent=2, ensure_ascii=False)
                
        except Exception as e:
            logger.error(f"保存状态文件失败: {e}")
    
    def update_kline_data(self, open_price: float, high_price: float, low_price: float, 
                          close_price: float, volume: float, timestamp: datetime = None) -> MarketState:
        """
        更新1小时K线数据并检测连续同向K线累计涨跌幅
        
        Args:
            open_price: 开盘价
            high_price: 最高价
            low_price: 最低价
            close_price: 收盘价
            volume: 成交量
            timestamp: K线时间戳
            
        Returns:
            MarketState: 当前市场状态
        """
        current_time = timestamp or datetime.now()
        
        # 计算K线涨跌幅和方向
        change_percent = ((close_price - open_price) / open_price) * 100
        if change_percent > 0.1:  # 上涨超过0.1%
            direction = 'up'
        elif change_percent < -0.1:  # 下跌超过0.1%
            direction = 'down'
        else:
            direction = 'neutral'
        
        # 创建K线数据
        kline_data = KlineData(
            timestamp=current_time,
            open_price=open_price,
            high_price=high_price,
            low_price=low_price,
            close_price=close_price,
            volume=volume,
            direction=direction,
            change_percent=change_percent
        )
        
        # 更新K线缓冲区
        self.kline_buffer.append(kline_data)
        if len(self.kline_buffer) > self.max_kline_buffer_size:
            self.kline_buffer.pop(0)
        
        # 检测连续同向K线趋势
        self._detect_consecutive_trend(kline_data)
        
        # 更新价格缓冲区(用于ATR计算)
        self.price_buffer.append((current_time, close_price))
        if len(self.price_buffer) > self.max_buffer_size:
            self.price_buffer.pop(0)
        
        # 计算ATR
        atr_value = self._calculate_atr()
        
        # 检测极端行情(基于连续同向K线累计涨跌幅)
        is_extreme = abs(self.cumulative_change_percent) >= self.config.extreme_threshold
        
        # 创建市场状态
        market_state = MarketState(
            timestamp=current_time,
            price=close_price,
            trend_start_price=self.consecutive_trend_start_price or close_price,
            trend_start_time=self.consecutive_trend_start_time or current_time,
            trend_direction=self.consecutive_trend_direction,
            trend_magnitude=self.cumulative_change_percent,
            consecutive_klines=self.consecutive_kline_count,
            atr_value=atr_value,
            is_extreme=is_extreme,
            protection_triggered=self.protection_active
        )
        
        return market_state
    
    def update_market_data(self, price: float, volume: float = None) -> MarketState:
        """
        更新市场数据并检测趋势
        
        Args:
            price: 当前价格
            volume: 成交量(可选)
            
        Returns:
            MarketState: 当前市场状态
        """
        current_time = datetime.now()
        
        # 更新价格缓冲区
        self.price_buffer.append((current_time, price))
        if len(self.price_buffer) > self.max_buffer_size:
            self.price_buffer.pop(0)
        
        # 计算ATR
        atr_value = self._calculate_atr()
        
        # 检测趋势转折点
        trend_info = self._detect_trend_change(price, current_time)
        
        # 计算当前趋势幅度
        trend_magnitude = 0.0
        if self.current_trend_start_price and self.current_trend_direction != 'neutral':
            trend_magnitude = ((price - self.current_trend_start_price) / self.current_trend_start_price) * 100
            if self.current_trend_direction == 'down':
                trend_magnitude = abs(trend_magnitude)
        
        # 检测极端行情
        is_extreme = abs(trend_magnitude) >= self.config.extreme_threshold
        
        # 创建市场状态(保持兼容性)
        market_state = MarketState(
            timestamp=current_time,
            price=price,
            trend_start_price=self.current_trend_start_price or price,
            trend_start_time=self.current_trend_start_time or current_time,
            trend_direction=self.current_trend_direction,
            trend_magnitude=trend_magnitude,
            consecutive_klines=0,  # 实时价格模式下设为0
            atr_value=atr_value,
            is_extreme=is_extreme,
            protection_triggered=self.protection_active
        )
        
        return market_state
    
    def _detect_consecutive_trend(self, kline_data: KlineData):
        """
        检测连续同向K线趋势并计算累计涨跌幅
        
        Args:
            kline_data: 当前K线数据
        """
        current_direction = kline_data.direction
        
        # 如果当前K线方向与连续趋势方向相同，继续累计
        if current_direction == self.consecutive_trend_direction and current_direction != 'neutral':
            self.consecutive_kline_count += 1
            
            # 计算从趋势开始到当前的累计涨跌幅
            if self.consecutive_trend_start_price:
                self.cumulative_change_percent = (
                    (kline_data.close_price - self.consecutive_trend_start_price) / 
                    self.consecutive_trend_start_price
                ) * 100
                
                # 对于下跌趋势，取绝对值
                if self.consecutive_trend_direction == 'down':
                    self.cumulative_change_percent = abs(self.cumulative_change_percent)
        
        # 如果方向改变或从neutral开始新趋势
        elif current_direction != 'neutral' and current_direction != self.consecutive_trend_direction:
            # 开始新的连续趋势
            self.consecutive_trend_direction = current_direction
            self.consecutive_trend_start_price = kline_data.open_price
            self.consecutive_trend_start_time = kline_data.timestamp
            self.consecutive_kline_count = 1
            
            # 计算初始累计涨跌幅
            self.cumulative_change_percent = abs(kline_data.change_percent)
            
            logger.info(f"开始新的连续{current_direction}趋势，起始价格: {kline_data.open_price}")
        
        # 如果是neutral K线，重置连续趋势
        elif current_direction == 'neutral':
            if self.consecutive_trend_direction != 'neutral':
                logger.info(f"连续{self.consecutive_trend_direction}趋势结束，"
                          f"持续{self.consecutive_kline_count}根K线，"
                          f"累计涨跌幅: {self.cumulative_change_percent:.2f}%")
            
            self._reset_consecutive_trend()
        
        # 记录当前状态
        logger.debug(f"连续趋势状态 - 方向: {self.consecutive_trend_direction}, "
                    f"K线数: {self.consecutive_kline_count}, "
                    f"累计涨跌幅: {self.cumulative_change_percent:.2f}%")
    
    def _reset_consecutive_trend(self):
        """重置连续趋势状态"""
        self.consecutive_trend_direction = 'neutral'
        self.consecutive_trend_start_price = None
        self.consecutive_trend_start_time = None
        self.consecutive_kline_count = 0
        self.cumulative_change_percent = 0.0
    
    def _calculate_atr(self, period: int = 14) -> float:
        """
        计算平均真实波幅(ATR)
        
        Args:
            period: ATR计算周期
            
        Returns:
            float: ATR值
        """
        if len(self.price_buffer) < period + 1:
            return 0.0
        
        true_ranges = []
        for i in range(1, min(len(self.price_buffer), period + 1)):
            current_price = self.price_buffer[-i][1]
            previous_price = self.price_buffer[-i-1][1]
            
            # 简化ATR计算(仅使用价格变化)
            true_range = abs(current_price - previous_price)
            true_ranges.append(true_range)
        
        if true_ranges:
            atr = sum(true_ranges) / len(true_ranges)
            
            # 更新ATR历史
            self.last_atr_values.append(atr)
            if len(self.last_atr_values) > 50:  # 保留最近50个ATR值
                self.last_atr_values.pop(0)
            
            # 设置基准ATR
            if self.baseline_atr is None and len(self.last_atr_values) >= 20:
                self.baseline_atr = sum(self.last_atr_values) / len(self.last_atr_values)
            
            return atr
        
        return 0.0
    
    def _detect_trend_change(self, current_price: float, current_time: datetime) -> Dict:
        """
        检测趋势变化
        
        Args:
            current_price: 当前价格
            current_time: 当前时间
            
        Returns:
            Dict: 趋势信息
        """
        if len(self.price_buffer) < self.config.trend_detection_window:
            return {'trend_changed': False}
        
        # 获取最近的价格数据
        recent_prices = [p[1] for p in self.price_buffer[-self.config.trend_detection_window:]]
        
        # 简单趋势检测：比较当前价格与窗口内的最高/最低价
        window_high = max(recent_prices)
        window_low = min(recent_prices)
        window_mid = (window_high + window_low) / 2
        
        new_direction = 'neutral'
        trend_changed = False
        
        # 判断趋势方向
        if current_price > window_mid * 1.02:  # 上涨趋势
            new_direction = 'up'
        elif current_price < window_mid * 0.98:  # 下跌趋势
            new_direction = 'down'
        
        # 检测趋势转折
        if new_direction != self.current_trend_direction and new_direction != 'neutral':
            trend_changed = True
            
            # 记录新趋势起点
            self.current_trend_direction = new_direction
            self.current_trend_start_price = current_price
            self.current_trend_start_time = current_time
            
            logger.info(f"检测到趋势转折: {new_direction}, 起始价格: {current_price}")
        
        return {
            'trend_changed': trend_changed,
            'new_direction': new_direction,
            'window_high': window_high,
            'window_low': window_low
        }
    
    async def check_extreme_protection(self, market_state: MarketState) -> bool:
        """
        检查是否需要触发极端防护
        
        Args:
            market_state: 市场状态
            
        Returns:
            bool: 是否触发了防护
        """
        # 如果已经在防护状态，检查是否可以解除
        if self.protection_active:
            return await self._check_hibernation_end(market_state)
        
        # 检查是否达到极端阈值(基于连续同向K线累计涨跌幅)
        if market_state.is_extreme and not self.protection_active:
            # 对于K线数据模式，检查连续K线数量
            if market_state.consecutive_klines > 0:
                logger.critical(f"检测到极端行情！连续{market_state.consecutive_klines}根{market_state.trend_direction}K线")
                logger.critical(f"累计涨跌幅: {market_state.trend_magnitude:.2f}%, 超过阈值{self.config.extreme_threshold}%")
                
                # 触发紧急防护
                success = await self._trigger_emergency_protection(market_state)
                return success
            # 对于实时价格模式，验证趋势持续时间
            elif market_state.trend_start_time:
                trend_duration = (market_state.timestamp - market_state.trend_start_time).total_seconds() / 60
                
                if trend_duration >= self.config.min_trend_duration:
                    logger.critical(f"检测到极端行情！趋势幅度: {market_state.trend_magnitude:.2f}%")
                    logger.critical(f"趋势方向: {market_state.trend_direction}, 持续时间: {trend_duration:.1f}分钟")
                    
                    # 触发紧急防护
                    success = await self._trigger_emergency_protection(market_state)
                    return success
        
        return False
    
    async def _trigger_emergency_protection(self, market_state: MarketState) -> bool:
        """
        触发紧急防护机制
        
        Args:
            market_state: 市场状态
            
        Returns:
            bool: 是否成功触发防护
        """
        try:
            logger.critical("=" * 60)
            logger.critical("触发极端行情紧急防护机制！")
            logger.critical(f"当前价格: {market_state.price}")
            logger.critical(f"趋势起始价格: {market_state.trend_start_price}")
            logger.critical(f"趋势幅度: {market_state.trend_magnitude:.2f}%")
            logger.critical(f"趋势方向: {market_state.trend_direction}")
            logger.critical("=" * 60)
            
            # 1. 立即停止所有新订单
            logger.critical("步骤1: 停止所有新订单")
            
            # 2. 取消所有挂单
            logger.critical("步骤2: 取消所有挂单")
            cancel_success = await self._cancel_all_orders()
            
            # 3. 紧急平仓所有持仓
            logger.critical("步骤3: 紧急平仓所有持仓")
            close_success = await self._emergency_close_all_positions(market_state.price)
            
            # 4. 激活休眠状态
            if cancel_success and close_success:
                self.protection_active = True
                self.hibernation_start_time = datetime.now()
                self._save_state()
                
                logger.critical(f"紧急防护激活成功！休眠开始时间: {self.hibernation_start_time}")
                logger.critical(f"预计恢复时间: {self.hibernation_start_time + timedelta(hours=self.config.hibernation_hours)}")
                
                return True
            else:
                logger.error("紧急防护执行失败！")
                return False
                
        except Exception as e:
            logger.error(f"触发紧急防护失败: {e}")
            return False
    
    async def _cancel_all_orders(self) -> bool:
        """
        取消所有挂单
        
        Returns:
            bool: 是否成功
        """
        try:
            # 获取所有开放订单
            open_orders = self.exchange.get_open_orders()
            
            if not open_orders:
                logger.info("没有需要取消的挂单")
                return True
            
            logger.info(f"发现 {len(open_orders)} 个挂单，开始取消...")
            
            cancel_tasks = []
            for order in open_orders:
                task = asyncio.create_task(self._cancel_single_order(order['id']))
                cancel_tasks.append(task)
            
            # 并发取消所有订单
            results = await asyncio.gather(*cancel_tasks, return_exceptions=True)
            
            success_count = sum(1 for r in results if r is True)
            logger.info(f"订单取消结果: {success_count}/{len(open_orders)} 成功")
            
            return success_count == len(open_orders)
            
        except Exception as e:
            logger.error(f"取消所有订单失败: {e}")
            return False
    
    async def _cancel_single_order(self, order_id: str) -> bool:
        """
        取消单个订单
        
        Args:
            order_id: 订单ID
            
        Returns:
            bool: 是否成功
        """
        try:
            self.exchange.cancel_order(order_id)
            return True
        except Exception as e:
            logger.error(f"取消订单 {order_id} 失败: {e}")
            return False
    
    async def _emergency_close_all_positions(self, current_price: float) -> bool:
        """
        紧急平仓所有持仓
        
        Args:
            current_price: 当前价格
            
        Returns:
            bool: 是否成功
        """
        try:
            # 获取当前持仓
            positions = self.exchange.get_position()
            
            if not positions:
                logger.info("没有需要平仓的持仓")
                return True
            
            close_tasks = []
            
            # 处理多头持仓
            long_position = positions.get('long', 0)
            if long_position > 0:
                # 使用市价单紧急平仓
                task = asyncio.create_task(
                    self._place_emergency_close_order('sell', long_position, current_price, 'long')
                )
                close_tasks.append(task)
            
            # 处理空头持仓
            short_position = positions.get('short', 0)
            if short_position > 0:
                # 使用市价单紧急平仓
                task = asyncio.create_task(
                    self._place_emergency_close_order('buy', short_position, current_price, 'short')
                )
                close_tasks.append(task)
            
            if not close_tasks:
                logger.info("没有需要平仓的持仓")
                return True
            
            # 并发执行平仓
            results = await asyncio.gather(*close_tasks, return_exceptions=True)
            
            success_count = sum(1 for r in results if r is True)
            logger.info(f"持仓平仓结果: {success_count}/{len(close_tasks)} 成功")
            
            return success_count == len(close_tasks)
            
        except Exception as e:
            logger.error(f"紧急平仓失败: {e}")
            return False
    
    async def _place_emergency_close_order(self, side: str, quantity: float, price: float, position_side: str) -> bool:
        """
        下紧急平仓订单
        
        Args:
            side: 订单方向 ('buy' or 'sell')
            quantity: 数量
            price: 价格
            position_side: 持仓方向 ('long' or 'short')
            
        Returns:
            bool: 是否成功
        """
        try:
            # 使用侵略性限价单确保成交
            if side == 'sell':
                aggressive_price = price * 0.995  # 降低0.5%
            else:
                aggressive_price = price * 1.005  # 提高0.5%
            
            logger.critical(f"紧急平仓 {position_side}: {side} {quantity} @ {aggressive_price}")
            
            # 下单
            order_result = self.exchange.place_order(
                side=side,
                price=aggressive_price,
                quantity=quantity,
                reduce_only=True,
                position_side=position_side,
                order_type='limit'
            )
            
            if order_result:
                logger.info(f"紧急平仓订单已下达: {order_result}")
                
                # 等待订单成交或超时
                await self._wait_for_order_fill(order_result.get('id'), self.config.emergency_close_timeout)
                return True
            else:
                logger.error(f"紧急平仓订单下达失败")
                return False
                
        except Exception as e:
            logger.error(f"下紧急平仓订单失败: {e}")
            return False
    
    async def _wait_for_order_fill(self, order_id: str, timeout: int):
        """
        等待订单成交
        
        Args:
            order_id: 订单ID
            timeout: 超时时间(秒)
        """
        start_time = time.time()
        
        while time.time() - start_time < timeout:
            try:
                order_status = self.exchange.get_order_status(order_id)
                
                if order_status and order_status.get('status') == 'filled':
                    logger.info(f"订单 {order_id} 已成交")
                    return True
                elif order_status and order_status.get('status') in ['canceled', 'rejected']:
                    logger.warning(f"订单 {order_id} 状态异常: {order_status.get('status')}")
                    return False
                
                await asyncio.sleep(1)
                
            except Exception as e:
                logger.error(f"检查订单状态失败: {e}")
                await asyncio.sleep(1)
        
        logger.warning(f"订单 {order_id} 等待成交超时")
        return False
    
    async def _check_hibernation_end(self, market_state: MarketState) -> bool:
        """
        检查是否可以结束休眠状态
        
        Args:
            market_state: 市场状态
            
        Returns:
            bool: 是否结束了休眠
        """
        if not self.hibernation_start_time:
            return False
        
        # 检查休眠时间是否已满
        hibernation_duration = datetime.now() - self.hibernation_start_time
        hibernation_hours = hibernation_duration.total_seconds() / 3600
        
        if hibernation_hours < self.config.hibernation_hours:
            # 休眠时间未满
            remaining_hours = self.config.hibernation_hours - hibernation_hours
            if int(hibernation_hours) % 6 == 0:  # 每6小时记录一次
                logger.info(f"休眠中... 剩余时间: {remaining_hours:.1f} 小时")
            return False
        
        # 休眠时间已满，检查ATR是否恢复正常
        if self._is_atr_recovered(market_state.atr_value):
            logger.info("休眠时间已满且ATR已恢复正常，准备重启网格")
            
            # 结束防护状态
            self.protection_active = False
            self.hibernation_start_time = None
            self._save_state()
            
            logger.critical("=" * 60)
            logger.critical("极端行情防护解除！")
            logger.critical(f"休眠时长: {hibernation_hours:.1f} 小时")
            logger.critical(f"当前ATR: {market_state.atr_value:.6f}")
            logger.critical(f"基准ATR: {self.baseline_atr:.6f}")
            logger.critical("网格策略即将重启...")
            logger.critical("=" * 60)
            
            return True
        else:
            logger.info(f"休眠时间已满但ATR未恢复正常，继续等待 (当前ATR: {market_state.atr_value:.6f})")
            return False
    
    def _is_atr_recovered(self, current_atr: float) -> bool:
        """
        检查ATR是否恢复正常
        
        Args:
            current_atr: 当前ATR值
            
        Returns:
            bool: 是否恢复正常
        """
        if not self.baseline_atr or current_atr <= 0:
            return False
        
        # ATR恢复到基准值的1.5倍以内认为正常
        recovery_threshold = self.baseline_atr * self.config.atr_recovery_multiplier
        
        return current_atr <= recovery_threshold
    
    def get_protection_status(self) -> Dict:
        """
        获取防护状态信息
        
        Returns:
            Dict: 防护状态
        """
        status = {
            'protection_active': self.protection_active,
            'hibernation_start_time': self.hibernation_start_time.isoformat() if self.hibernation_start_time else None,
            'baseline_atr': self.baseline_atr,
            'current_trend_direction': self.current_trend_direction,
            'current_trend_start_price': self.current_trend_start_price,
            'config': {
                'extreme_threshold': self.config.extreme_threshold,
                'hibernation_hours': self.config.hibernation_hours,
                'atr_recovery_multiplier': self.config.atr_recovery_multiplier
            }
        }
        
        if self.hibernation_start_time:
            hibernation_duration = datetime.now() - self.hibernation_start_time
            status['hibernation_hours_elapsed'] = hibernation_duration.total_seconds() / 3600
            status['hibernation_hours_remaining'] = max(0, self.config.hibernation_hours - status['hibernation_hours_elapsed'])
        
        return status
    
    def is_protection_active(self) -> bool:
        """
        检查防护是否激活
        
        Returns:
            bool: 防护是否激活
        """
        return self.protection_active
    
    def force_reset_protection(self):
        """
        强制重置防护状态(仅用于紧急情况)
        """
        logger.warning("强制重置极端行情防护状态")
        
        self.protection_active = False
        self.hibernation_start_time = None
        self.current_trend_direction = 'neutral'
        self.current_trend_start_price = None
        self.current_trend_start_time = None
        
        self._save_state()
        
        logger.warning("防护状态已强制重置")

# 使用示例
if __name__ == "__main__":
    # 这里是测试代码，实际使用时应该集成到主交易系统中
    pass