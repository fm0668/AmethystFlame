#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
网格策略核心模块
包含网格逻辑和订单管理
"""

import asyncio
import time
import logging
from config import config
from exchange_interface import ExchangeInterface

logger = logging.getLogger(__name__)

class GridCore:
    """网格策略核心类"""
    
    def __init__(self, exchange_interface: ExchangeInterface):
        self.lock = asyncio.Lock()  # 初始化线程锁
        self.exchange = exchange_interface
        
        # 持仓状态
        self.long_initial_quantity = 0  # 多头下单数量
        self.short_initial_quantity = 0  # 空头下单数量
        self.long_position = 0  # 多头持仓
        self.short_position = 0  # 空头持仓
        
        # 订单状态
        self.buy_long_orders = 0.0  # 多头买入剩余挂单数量
        self.sell_long_orders = 0.0  # 多头卖出剩余挂单数量
        self.sell_short_orders = 0.0  # 空头卖出剩余挂单数量
        self.buy_short_orders = 0.0  # 空头买入剩余挂单数量
        
        # 时间控制
        self.last_long_order_time = 0  # 上次多头挂单时间
        self.last_short_order_time = 0  # 上次空头挂单时间
        self.last_position_update_time = 0  # 上次持仓更新时间
        self.last_orders_update_time = 0  # 上次订单更新时间
        
        # 价格相关
        self.latest_price = 0  # 最新价格
        self.best_bid_price = None  # 最佳买价
        self.best_ask_price = None  # 最佳卖价
        
        # 网格价格
        self.mid_price_long = 0  # long 中间价
        self.lower_price_long = 0  # long 网格下
        self.upper_price_long = 0  # long 网格上
        self.mid_price_short = 0  # short 中间价
        self.lower_price_short = 0  # short 网格下
        self.upper_price_short = 0  # short 网格上
        
        # 动态网格间距支持
        self.long_grid_spacing = config.GRID_SPACING  # 做多网格间距
        self.short_grid_spacing = config.GRID_SPACING  # 做空网格间距
        self.long_profit_spacing = config.GRID_SPACING  # 做多止盈间距
        self.short_profit_spacing = config.GRID_SPACING  # 做空止盈间距
    
    def check_orders_status(self):
        """检查当前所有挂单的状态，并更新多头和空头的挂单数量"""
        orders = self.exchange.fetch_open_orders()
        
        # 初始化计数器
        buy_long_orders = 0.0
        sell_long_orders = 0.0
        buy_short_orders = 0.0
        sell_short_orders = 0.0
        
        for order in orders:
            # 获取订单的原始委托数量（取绝对值）
            orig_quantity = abs(float(order.get('info', {}).get('origQty', 0)))
            side = order.get('side')  # 订单方向：buy 或 sell
            position_side = order.get('info', {}).get('positionSide')  # 仓位方向：LONG 或 SHORT
            
            # 判断订单类型
            if side == 'buy' and position_side == 'LONG':  # 多头买单
                buy_long_orders += orig_quantity
            elif side == 'sell' and position_side == 'LONG':  # 多头卖单
                sell_long_orders += orig_quantity
            elif side == 'buy' and position_side == 'SHORT':  # 空头买单
                buy_short_orders += orig_quantity
            elif side == 'sell' and position_side == 'SHORT':  # 空头卖单
                sell_short_orders += orig_quantity
        
        # 更新实例变量
        self.buy_long_orders = buy_long_orders
        self.sell_long_orders = sell_long_orders
        self.buy_short_orders = buy_short_orders
        self.sell_short_orders = sell_short_orders
    
    def cancel_orders_for_side(self, position_side):
        """撤销某个方向的所有挂单"""
        orders = self.exchange.fetch_open_orders()
        
        if len(orders) == 0:
            logger.info("没有找到挂单")
        else:
            try:
                for order in orders:
                    # 获取订单的方向和仓位方向
                    side = order.get('side')  # 订单方向：buy 或 sell
                    reduce_only = order.get('reduceOnly', False)  # 是否为平仓单
                    position_side_order = order.get('info', {}).get('positionSide', 'BOTH')  # 仓位方向
                    
                    if position_side == 'long':
                        # 如果是多头开仓订单：买单且 reduceOnly 为 False
                        if not reduce_only and side == 'buy' and position_side_order == 'LONG':
                            self.exchange.cancel_order(order['id'])
                        # 如果是多头止盈订单：卖单且 reduceOnly 为 True
                        elif reduce_only and side == 'sell' and position_side_order == 'LONG':
                            self.exchange.cancel_order(order['id'])
                    
                    elif position_side == 'short':
                        # 如果是空头开仓订单：卖单且 reduceOnly 为 False
                        if not reduce_only and side == 'sell' and position_side_order == 'SHORT':
                            self.exchange.cancel_order(order['id'])
                        # 如果是空头止盈订单：买单且 reduceOnly 为 True
                        elif reduce_only and side == 'buy' and position_side_order == 'SHORT':
                            self.exchange.cancel_order(order['id'])
            except Exception as e:
                logger.error(f"撤单失败: {e}")
                self.check_orders_status()  # 强制更新挂单状态
    
    def update_mid_price(self, position_side, latest_price):
        """更新中间价和网格价格"""
        if position_side == 'long':
            self.mid_price_long = latest_price
            # 使用动态网格间距：补仓使用long_grid_spacing，止盈使用long_profit_spacing
            self.lower_price_long = self.mid_price_long * (1 - self.long_grid_spacing)  # 补仓价格
            self.upper_price_long = self.mid_price_long * (1 + self.long_profit_spacing)  # 止盈价格
        elif position_side == 'short':
            self.mid_price_short = latest_price
            # 使用动态网格间距：补仓使用short_grid_spacing，止盈使用short_profit_spacing
            self.lower_price_short = self.mid_price_short * (1 - self.short_profit_spacing)  # 止盈价格
            self.upper_price_short = self.mid_price_short * (1 + self.short_grid_spacing)  # 补仓价格
    
    def get_take_profit_quantity(self, position, position_side):
        """计算止盈数量"""
        if position_side == 'long':
            # 如果持仓超过POSITION_LIMIT，使用双倍止盈数量
            if position > config.POSITION_LIMIT:  # 200 XRP
                self.long_initial_quantity = min(position, config.INITIAL_QUANTITY * 2)  # 3 * 2 = 6 XRP
            else:
                self.long_initial_quantity = min(position, config.INITIAL_QUANTITY)  # 3 XRP
        elif position_side == 'short':
            # 如果持仓超过POSITION_LIMIT，使用双倍止盈数量
            if position > config.POSITION_LIMIT:  # 200 XRP
                self.short_initial_quantity = min(position, config.INITIAL_QUANTITY * 2)  # 3 * 2 = 6 XRP
            else:
                self.short_initial_quantity = min(position, config.INITIAL_QUANTITY)  # 3 XRP
    
    async def initialize_long_orders(self):
        """初始化多头挂单"""
        # 检查上次挂单时间，确保间隔足够
        current_time = time.time()
        if current_time - self.last_long_order_time < config.ORDER_FIRST_TIME:
            logger.info(f"距离上次多头挂单时间不足 {config.ORDER_FIRST_TIME} 秒，跳过本次挂单")
            return
        
        # 撤销所有多头挂单
        self.cancel_orders_for_side('long')
        
        # 挂出多头开仓单
        self.exchange.place_order('buy', self.best_bid_price, config.INITIAL_QUANTITY, False, 'long')
        logger.info(f"挂出多头开仓单: 买入 @ {self.latest_price}")
        
        # 更新上次多头挂单时间
        self.last_long_order_time = time.time()
        logger.info("初始化多头挂单完成")
    
    async def initialize_short_orders(self):
        """初始化空头挂单"""
        # 检查上次挂单时间，确保间隔足够
        current_time = time.time()
        if current_time - self.last_short_order_time < config.ORDER_FIRST_TIME:
            logger.info(f"距离上次空头挂单时间不足 {config.ORDER_FIRST_TIME} 秒，跳过本次挂单")
            return
        
        # 撤销所有空头挂单
        self.cancel_orders_for_side('short')
        
        # 挂出空头开仓单
        self.exchange.place_order('sell', self.best_ask_price, config.INITIAL_QUANTITY, False, 'short')
        logger.info(f"挂出空头开仓单: 卖出 @ {self.latest_price}")
        
        # 更新上次空头挂单时间
        self.last_short_order_time = time.time()
        logger.info("初始化空头挂单完成")
    
    async def place_long_orders(self, latest_price):
        """挂多头订单"""
        try:
            self.get_take_profit_quantity(self.long_position, 'long')
            
            if self.long_position > 0:
                # 检查持仓是否超过阈值
                if self.long_position > config.POSITION_THRESHOLD:
                    logger.info(f"多头持仓 {self.long_position} 超过阈值 {config.POSITION_THRESHOLD}，进入保守模式")
                    if self.sell_long_orders <= 0:
                        # 计算保守止盈价格
                        ratio = float((self.long_position / max(self.short_position, 1)) / 100 + 1)
                        profit_price = self.latest_price * ratio
                        self.exchange.place_take_profit_order('long', profit_price, self.long_initial_quantity)
                else:
                    # 正常网格模式
                    self.update_mid_price('long', latest_price)
                    self.cancel_orders_for_side('long')
                    
                    # 挂止盈单
                    self.exchange.place_take_profit_order('long', self.upper_price_long, self.long_initial_quantity)
                    
                    # 挂补仓单
                    self.exchange.place_order('buy', self.lower_price_long, self.long_initial_quantity, False, 'long')
                    
                    logger.info("挂多头止盈单和补仓单")
        
        except Exception as e:
            logger.error(f"挂多头订单失败: {e}")
    
    async def place_short_orders(self, latest_price):
        """挂空头订单"""
        try:
            self.get_take_profit_quantity(self.short_position, 'short')
            
            if self.short_position > 0:
                # 检查持仓是否超过阈值
                if self.short_position > config.POSITION_THRESHOLD:
                    logger.info(f"空头持仓 {self.short_position} 超过阈值 {config.POSITION_THRESHOLD}，进入保守模式")
                    if self.buy_short_orders <= 0:
                        # 计算保守止盈价格
                        ratio = float((self.short_position / max(self.long_position, 1)) / 100 + 1)
                        profit_price = self.latest_price / ratio
                        self.exchange.place_take_profit_order('short', profit_price, self.short_initial_quantity)
                else:
                    # 正常网格模式
                    self.update_mid_price('short', latest_price)
                    self.cancel_orders_for_side('short')
                    
                    # 挂止盈单
                    self.exchange.place_take_profit_order('short', self.lower_price_short, self.short_initial_quantity)
                    
                    # 挂补仓单
                    self.exchange.place_order('sell', self.upper_price_short, self.short_initial_quantity, False, 'short')
                    
                    logger.info("挂空头止盈单和补仓单")
        
        except Exception as e:
            logger.error(f"挂空头订单失败: {e}")
    
    def check_and_reduce_positions(self):
        """检查并减少持仓（风控逻辑）"""
        try:
            # 如果双向持仓都超过阈值，进行风控处理
            if (self.long_position > config.POSITION_THRESHOLD and 
                self.short_position > config.POSITION_THRESHOLD):
                
                logger.warning(f"双向持仓均超过阈值，多头: {self.long_position}, 空头: {self.short_position}")
                
                # 计算需要平仓的数量（取较小持仓的一半）
                reduce_quantity = min(self.long_position, self.short_position) * 0.5
                
                if reduce_quantity > 0:
                    # 侵略性平仓逻辑
                    aggressive_sell_price = self.latest_price * 0.999  # 稍低于市价卖出
                    aggressive_buy_price = self.latest_price * 1.001   # 稍高于市价买入
                    
                    # 平多头仓位
                    self.exchange.place_order('sell', aggressive_sell_price, reduce_quantity, True, 'long', 'limit')
                    logger.info(f"侵略性限价平仓多头 {reduce_quantity} @ {aggressive_sell_price}")
                    
                    # 平空头仓位
                    self.exchange.place_order('buy', aggressive_buy_price, reduce_quantity, True, 'short', 'limit')
                    logger.info(f"侵略性限价平仓空头 {reduce_quantity} @ {aggressive_buy_price}")
        
        except Exception as e:
            logger.error(f"检查和减少持仓失败: {e}")
    
    async def adjust_grid_strategy(self):
        """根据最新价格和持仓调整网格策略"""
        # 检查双向仓位库存，如果同时达到，就统一部分平仓减少库存风险
        self.check_and_reduce_positions()
        
        # 检测多头持仓
        if self.long_position == 0:
            logger.info(f"检测到没有多头持仓{self.long_position}，初始化多头挂单@ ticker")
            await self.initialize_long_orders()
        else:
            orders_valid = not (0 < self.buy_long_orders <= self.long_initial_quantity) or \
                          not (0 < self.sell_long_orders <= self.long_initial_quantity)
            if orders_valid:
                if self.long_position < config.POSITION_THRESHOLD:
                    logger.info('如果 long 持仓没到阈值，同步后再次确认！')
                    self.check_orders_status()
                    if orders_valid:
                        await self.place_long_orders(self.latest_price)
                else:
                    await self.place_long_orders(self.latest_price)
        
        # 检测空头持仓
        if self.short_position == 0:
            await self.initialize_short_orders()
        else:
            # 检查订单数量是否在合理范围内
            orders_valid = not (0 < self.sell_short_orders <= self.short_initial_quantity) or \
                          not (0 < self.buy_short_orders <= self.short_initial_quantity)
            if orders_valid:
                if self.short_position < config.POSITION_THRESHOLD:
                    logger.info('如果 short 持仓没到阈值，同步后再次确认！')
                    self.check_orders_status()
                    if orders_valid:
                        await self.place_short_orders(self.latest_price)
                else:
                    await self.place_short_orders(self.latest_price)