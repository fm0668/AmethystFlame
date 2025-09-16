#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
XRP网格交易策略 - 主程序
币安合约网格交易机器人
模块化重构版本 v5.0
"""

import asyncio
import json
import logging
import sys
import time
import websockets
from config import config
from exchange_interface import ExchangeInterface
from grid_core import GridCore
from extreme_market_protection import ExtremeMarketProtection
from ema_adx_signal_module import EMAAdxSignalModule
from grid_scheduler import grid_scheduler, add_trade_record
from grid_summary_module import grid_summary

# 配置日志
logging.basicConfig(
    level=getattr(logging, config.LOG_LEVEL),
    format=config.LOG_FORMAT,
    handlers=[
        logging.FileHandler(config.LOG_FILE, encoding='utf-8'),
        logging.StreamHandler(sys.stdout)
    ]
)

logger = logging.getLogger(__name__)

class GridTradingBot:
    """网格交易机器人主类"""
    
    def __init__(self):
        # 初始化组件
        self.exchange_interface = ExchangeInterface()
        self.grid_core = GridCore(self.exchange_interface)
        
        # 初始化极端行情防护
        self.extreme_protection = ExtremeMarketProtection()
        self.is_sleeping = False  # 休眠状态标志
        self.sleep_start_time = 0  # 休眠开始时间
        
        # 初始化EMA+ADX信号模块
        self.signal_module = EMAAdxSignalModule(
            ema_short=config.EMA_SHORT_PERIOD,
            ema_medium=config.EMA_MEDIUM_PERIOD,
            ema_long=config.EMA_LONG_PERIOD,
            adx_period=config.ADX_PERIOD,
            adx_threshold=config.ADX_THRESHOLD
        )
        self.last_signal_check_time = 0  # 信号检查时间限速
        
        # WebSocket相关
        self.listen_key = None
        self.last_ticker_update_time = 0  # ticker 时间限速
        
        # 添加锁机制用于订单更新处理
        self.lock = asyncio.Lock()
        
        # 初始化汇总功能
        self.config = config  # 提供配置访问
        grid_scheduler.set_grid_strategy(self)
        
        # 初始化交易所
        self._initialize()
    
    def _initialize(self):
        """初始化机器人"""
        try:
            # 打印配置信息
            config.print_config()
            
            # 初始化交易所连接
            self.exchange_interface.initialize_exchange()
            
            # 检查并启用双向持仓模式
            hedge_mode_enabled = self.exchange_interface.check_and_enable_hedge_mode()
            if not hedge_mode_enabled:
                logger.warning("双向持仓模式未启用，程序将在单向模式下运行")
            
            # 获取 listenKey
            try:
                self.listen_key = self.exchange_interface.get_listen_key()
                logger.info("获取listenKey成功")
            except Exception as e:
                logger.warning(f"获取listenKey失败: {e}，将使用轮询模式")
                self.listen_key = None
            
            logger.info("网格交易机器人初始化完成")
            
        except Exception as e:
            logger.error(f"初始化失败: {e}")
            raise
    
    async def keep_listen_key_alive(self):
        """保持 listenKey 活跃"""
        if not self.listen_key:
            return
            
        while True:
            try:
                await asyncio.sleep(1800)  # 每30分钟续期一次
                self.exchange_interface.keep_listen_key_alive(self.listen_key)
                logger.info("listenKey续期成功")
            except Exception as e:
                logger.error(f"listenKey续期失败: {e}")
                # 添加重试机制
                await asyncio.sleep(60)  # 等待60秒后重试
                try:
                    self.exchange_interface.keep_listen_key_alive(self.listen_key)
                    logger.info("listenKey续期重试成功")
                except Exception as retry_e:
                    logger.error(f"listenKey续期重试失败: {retry_e}")
    
    async def monitor_orders(self):
        """监控挂单状态，超过300秒未成交的挂单自动取消"""
        while True:
            try:
                await asyncio.sleep(60)  # 每60秒检查一次
                current_time = time.time()
                orders = self.exchange_interface.fetch_open_orders()
                
                if not orders:
                    logger.info("当前没有未成交的挂单")
                    # 重置挂单计数
                    self.grid_core.buy_long_orders = 0.0
                    self.grid_core.sell_long_orders = 0.0
                    self.grid_core.sell_short_orders = 0.0
                    self.grid_core.buy_short_orders = 0.0
                    continue
                
                for order in orders:
                    order_id = order['id']
                    order_timestamp = order.get('timestamp')
                    create_time = float(order['info'].get('create_time', 0))
                    
                    # 优先使用 create_time，如果不存在则使用 timestamp
                    order_time = create_time if create_time > 0 else order_timestamp / 1000
                    
                    if not order_time:
                        logger.warning(f"订单 {order_id} 缺少时间戳，无法检查超时")
                        continue
                    
                    if current_time - order_time > 300:  # 超过300秒未成交
                        logger.info(f"订单 {order_id} 超过300秒未成交，取消挂单")
                        try:
                            self.exchange_interface.cancel_order(order_id)
                        except Exception as e:
                            logger.error(f"取消订单 {order_id} 失败: {e}")
            
            except Exception as e:
                logger.error(f"监控挂单状态失败: {e}")
    
    async def subscribe_ticker(self, websocket):
        """订阅 ticker 数据"""
        payload = {
            "method": "SUBSCRIBE",
            "params": [f"{config.COIN_NAME.lower()}{config.CONTRACT_TYPE.lower()}@bookTicker"],
            "id": 1
        }
        await websocket.send(json.dumps(payload))
        logger.info(f"订阅 {config.COIN_NAME} ticker 数据")
    
    async def subscribe_orders(self, websocket):
        """订阅挂单数据"""
        if not self.listen_key:
            logger.warning("没有listenKey，无法订阅挂单数据")
            return
            
        payload = {
            "method": "SUBSCRIBE",
            "params": [self.listen_key],
            "id": 2
        }
        await websocket.send(json.dumps(payload))
        logger.info("订阅挂单数据")
    
    async def handle_ticker_update(self, message):
        """处理 ticker 更新"""
        try:
            data = json.loads(message)
            
            # 更新价格信息，添加价格有效性验证
            best_bid = data.get('b', 0)
            best_ask = data.get('a', 0)
            
            # 验证价格数据的有效性
            if not best_bid or not best_ask or float(best_bid) <= 0 or float(best_ask) <= 0:
                logger.warning(f"收到无效的ticker数据: bid={best_bid}, ask={best_ask}")
                return
            
            self.grid_core.best_bid_price = float(best_bid)
            self.grid_core.best_ask_price = float(best_ask)
            
            # 计算中间价并验证合理性
            new_price = (self.grid_core.best_bid_price + self.grid_core.best_ask_price) / 2
            
            # 价格合理性检查
            if hasattr(self.grid_core, 'latest_price') and self.grid_core.latest_price > 0:
                price_change_ratio = abs(new_price - self.grid_core.latest_price) / self.grid_core.latest_price
                if price_change_ratio > 0.1:  # 10%的价格变化阈值
                    logger.warning(f"价格变化异常: {self.grid_core.latest_price} -> {new_price}, 变化幅度: {price_change_ratio:.2%}")
                    # 如果价格变化过大，可以选择不更新或使用平滑处理
                    # 这里选择继续使用新价格，但记录警告
            
            self.grid_core.latest_price = new_price
            
            # 更新交易所接口的WebSocket价格
            self.exchange_interface.update_websocket_price(new_price)
            
            # 时间限速，避免过于频繁的处理
            current_time = time.time()
            if current_time - self.last_ticker_update_time < 1:  # 1秒限制
                return
            
            self.last_ticker_update_time = current_time
            
            # 【最高优先级】检查是否处于休眠状态
            if self.is_sleeping:
                if current_time - self.sleep_start_time < 24 * 3600:  # 24小时休眠
                    return  # 休眠期间不执行任何交易逻辑
                else:
                    # 休眠结束，重置状态
                    self.is_sleeping = False
                    self.sleep_start_time = 0
                    logger.info("24小时休眠结束，恢复正常交易")
            
            # 【最高优先级】极端行情防护检测
            market_state = self.extreme_protection.update_market_data(self.grid_core.latest_price)
            if market_state.is_extreme:
                await self.trigger_emergency_protection()
                return  # 触发紧急防护后立即返回，不执行后续逻辑
            
            # 定期同步持仓（每30秒）
            if current_time - self.grid_core.last_position_update_time > 30:
                long_pos, short_pos = self.exchange_interface.get_position()
                self.grid_core.long_position = long_pos
                self.grid_core.short_position = short_pos
                self.grid_core.last_position_update_time = current_time
                logger.info(f"同步持仓: 多头 {long_pos} 张, 空头 {short_pos} 张 @ ticker")
            
            # 定期同步订单状态（每60秒）
            if current_time - self.grid_core.last_orders_update_time > 60:
                self.grid_core.check_orders_status()
                self.grid_core.last_orders_update_time = current_time
                logger.info(f"定期同步订单状态 @ ticker")
            
            # EMA+ADX信号检测（每小时检查一次）
            if current_time - self.last_signal_check_time > 3600:  # 1小时
                await self.update_signal_and_adjust_grid()
                self.last_signal_check_time = current_time
            
            # 触发网格策略调整
            await self.grid_core.adjust_grid_strategy()
            
        except Exception as e:
            logger.error(f"处理ticker更新失败: {e}")
    
    async def update_signal_and_adjust_grid(self):
        """更新EMA+ADX信号并调整网格参数"""
        try:
            # 获取历史K线数据用于信号计算
            klines = self.exchange_interface.get_klines(timeframe='1h', limit=300)  # 获取300根1小时K线
            
            if not klines or len(klines) < 200:  # 确保有足够数据计算EMA200
                logger.warning("K线数据不足，跳过信号检测")
                return
            
            # 转换为DataFrame格式
            import pandas as pd
            from datetime import datetime
            
            df_data = []
            for kline in klines:
                df_data.append({
                    'timestamp': datetime.fromtimestamp(kline[0] / 1000),
                    'open': float(kline[1]),
                    'high': float(kline[2]),
                    'low': float(kline[3]),
                    'close': float(kline[4]),
                    'volume': float(kline[5])
                })
            
            df = pd.DataFrame(df_data)
            df.set_index('timestamp', inplace=True)
            
            # 更新信号模块数据缓存
            self.signal_module.data_buffer = df
            
            # 计算当前信号
            signal_info = self.signal_module.calculate_signals()
            
            # 检查信号变化
            old_signal = self.signal_module.current_signal
            new_signal = signal_info['signal']
            
            if new_signal != old_signal:
                self.signal_module.current_signal = new_signal
                self.signal_module.signal_start_time = datetime.now()
                
                logger.info(f"信号变化检测: {old_signal} -> {new_signal} ({signal_info['signal_name']})")
                logger.info(f"信号详情: ADX={signal_info['adx_value']}, 置信度={signal_info['confidence']}%")
                
                # 获取网格调整建议
                adjustment = self.signal_module.get_grid_adjustment_recommendation()
                logger.info(f"网格调整建议: {adjustment['recommendation']}")
                
                # 应用网格调整
                await self.apply_grid_adjustment(adjustment)
            else:
                logger.debug(f"信号无变化: {signal_info['signal_name']} (ADX={signal_info['adx_value']})")
                
        except Exception as e:
            logger.error(f"信号检测和网格调整失败: {e}")
    
    async def apply_grid_adjustment(self, adjustment):
        """应用网格调整建议"""
        try:
            # 获取当前网格参数
            original_long_spacing = self.grid_core.long_grid_spacing
            original_short_spacing = self.grid_core.short_grid_spacing
            original_long_profit = self.grid_core.long_profit_spacing
            original_short_profit = self.grid_core.short_profit_spacing
            
            # 计算新的网格间距
            new_long_spacing = original_long_spacing * adjustment['long_grid_spacing_multiplier']
            new_short_spacing = original_short_spacing * adjustment['short_grid_spacing_multiplier']
            new_long_profit = original_long_profit * adjustment['long_profit_spacing_multiplier']
            new_short_profit = original_short_profit * adjustment['short_profit_spacing_multiplier']
            
            logger.info(f"应用网格调整: {adjustment['adjust_type']}")
            logger.info(f"做多补仓间距: {original_long_spacing:.4f} -> {new_long_spacing:.4f} (倍数: {adjustment['long_grid_spacing_multiplier']})")
            logger.info(f"做空补仓间距: {original_short_spacing:.4f} -> {new_short_spacing:.4f} (倍数: {adjustment['short_grid_spacing_multiplier']})")
            logger.info(f"做多止盈间距: {original_long_profit:.4f} -> {new_long_profit:.4f} (倍数: {adjustment['long_profit_spacing_multiplier']})")
            logger.info(f"做空止盈间距: {original_short_profit:.4f} -> {new_short_profit:.4f} (倍数: {adjustment['short_profit_spacing_multiplier']})")
            
            # 更新网格核心的间距参数
            self.grid_core.long_grid_spacing = new_long_spacing
            self.grid_core.short_grid_spacing = new_short_spacing
            self.grid_core.long_profit_spacing = new_long_profit
            self.grid_core.short_profit_spacing = new_short_profit
            
            logger.info(f"网格参数调整完成: {adjustment['recommendation']}")
            
        except Exception as e:
            logger.error(f"应用网格调整失败: {e}")
    
    async def trigger_emergency_protection(self):
        """触发紧急防护：平仓所有持仓，撤销所有挂单，进入24小时休眠"""
        try:
            current_time = time.time()
            
            logger.critical(f"【紧急风控触发】检测到极端行情，当前价格: {self.grid_core.latest_price}")
            
            # 1. 撤销所有挂单
            try:
                orders = self.exchange_interface.fetch_open_orders()
                if orders:
                    logger.warning(f"撤销所有挂单，共{len(orders)}个订单")
                    for order in orders:
                        try:
                            self.exchange_interface.cancel_order(order['id'])
                        except Exception as e:
                            logger.error(f"撤销订单{order['id']}失败: {e}")
                else:
                    logger.info("当前无挂单需要撤销")
            except Exception as e:
                logger.error(f"撤销挂单失败: {e}")
            
            # 2. 平仓所有持仓
            try:
                long_pos, short_pos = self.exchange_interface.get_position()
                
                # 平多头持仓
                if long_pos > 0:
                    logger.warning(f"平仓多头持仓: {long_pos}张")
                    self.exchange_interface.place_order('sell', 0, long_pos, True, 'long')
                
                # 平空头持仓
                if short_pos > 0:
                    logger.warning(f"平仓空头持仓: {short_pos}张")
                    self.exchange_interface.place_order('buy', 0, short_pos, True, 'short')
                
                if long_pos == 0 and short_pos == 0:
                    logger.info("当前无持仓需要平仓")
                    
            except Exception as e:
                logger.error(f"平仓操作失败: {e}")
            
            # 3. 进入24小时休眠状态
            self.is_sleeping = True
            self.sleep_start_time = current_time
            
            # 4. 重置网格状态
            self.grid_core.buy_long_orders = 0.0
            self.grid_core.sell_long_orders = 0.0
            self.grid_core.sell_short_orders = 0.0
            self.grid_core.buy_short_orders = 0.0
            self.grid_core.long_position = 0
            self.grid_core.short_position = 0
            
            logger.critical(f"【紧急风控执行完成】已平仓所有持仓，撤销所有挂单，进入24小时休眠状态")
            
        except Exception as e:
            logger.error(f"紧急防护执行失败: {e}")
    
    async def handle_order_update(self, message):
        """处理挂单更新"""
        async with self.lock:  # 添加锁机制
            try:
                data = json.loads(message)
                order_data = data.get('o', {})
                
                # 获取订单信息
                symbol = order_data.get('s')
                side = order_data.get('S')  # BUY 或 SELL
                position_side = order_data.get('ps')  # LONG 或 SHORT
                order_status = order_data.get('X')  # 订单状态
                execution_type = order_data.get('x')  # 执行类型
                quantity = float(order_data.get('q', 0))  # 订单数量
                filled = float(order_data.get('z', 0))  # 已成交数量
                remaining = quantity - filled  # 剩余数量
                
                # 只处理我们关注的交易对
                expected_symbol = f"{config.COIN_NAME}{config.CONTRACT_TYPE}"
                if symbol != expected_symbol:
                    return
                
                logger.info(f"订单更新: {side} {position_side} {order_status} 数量:{quantity} 成交:{filled}")
                
                # 详细的订单状态处理
                if order_status == "NEW":
                    # 新订单创建时更新挂单数量
                    self._update_pending_orders(side, position_side, remaining, "add")
                elif order_status == "FILLED":
                    # 订单完全成交时更新持仓和挂单
                    self._update_position_and_orders(side, position_side, filled)
                elif order_status in ["CANCELED", "EXPIRED"]:
                    # 订单取消或过期时更新挂单数量
                    self._update_pending_orders(side, position_side, remaining, "remove")
                
                # 如果订单完全成交或取消，更新挂单状态
                if order_status in ['FILLED', 'CANCELED', 'EXPIRED']:
                    self.grid_core.check_orders_status()
                    
                    # 如果是成交，同步持仓
                    if order_status == 'FILLED':
                        long_pos, short_pos = self.exchange_interface.get_position()
                        self.grid_core.long_position = long_pos
                        self.grid_core.short_position = short_pos
                        logger.info(f"订单成交，同步持仓: 多头 {long_pos} 张, 空头 {short_pos} 张")
            
            except Exception as e:
                logger.error(f"处理挂单更新失败: {e}")
    
    def _update_pending_orders(self, side, position_side, quantity, action):
        """更新挂单数量"""
        try:
            if action == "add":
                if side == "BUY" and position_side == "LONG":
                    self.grid_core.buy_long_orders += quantity
                elif side == "SELL" and position_side == "LONG":
                    self.grid_core.sell_long_orders += quantity
                elif side == "BUY" and position_side == "SHORT":
                    self.grid_core.buy_short_orders += quantity
                elif side == "SELL" and position_side == "SHORT":
                    self.grid_core.sell_short_orders += quantity
            elif action == "remove":
                if side == "BUY" and position_side == "LONG":
                    self.grid_core.buy_long_orders = max(0.0, self.grid_core.buy_long_orders - quantity)
                elif side == "SELL" and position_side == "LONG":
                    self.grid_core.sell_long_orders = max(0.0, self.grid_core.sell_long_orders - quantity)
                elif side == "BUY" and position_side == "SHORT":
                    self.grid_core.buy_short_orders = max(0.0, self.grid_core.buy_short_orders - quantity)
                elif side == "SELL" and position_side == "SHORT":
                    self.grid_core.sell_short_orders = max(0.0, self.grid_core.sell_short_orders - quantity)
        except Exception as e:
            logger.error(f"更新挂单数量失败: {e}")

    def _update_position_and_orders(self, side, position_side, filled_quantity):
        """更新持仓和挂单状态"""
        try:
            if side == "BUY":
                if position_side == "LONG":  # 多头开仓单
                    self.grid_core.long_position += filled_quantity
                    self.grid_core.buy_long_orders = max(0.0, self.grid_core.buy_long_orders - filled_quantity)
                elif position_side == "SHORT":  # 空头止盈单
                    self.grid_core.short_position = max(0.0, self.grid_core.short_position - filled_quantity)
                    self.grid_core.buy_short_orders = max(0.0, self.grid_core.buy_short_orders - filled_quantity)
            elif side == "SELL":
                if position_side == "LONG":  # 多头止盈单
                    self.grid_core.long_position = max(0.0, self.grid_core.long_position - filled_quantity)
                    self.grid_core.sell_long_orders = max(0.0, self.grid_core.sell_long_orders - filled_quantity)
                elif position_side == "SHORT":  # 空头开仓单
                    self.grid_core.short_position += filled_quantity
                    self.grid_core.sell_short_orders = max(0.0, self.grid_core.sell_short_orders - filled_quantity)
        except Exception as e:
            logger.error(f"更新持仓和挂单状态失败: {e}")
    
    async def connect_websocket(self):
        """连接 WebSocket 并订阅 ticker 和持仓数据"""
        try:
            # 添加连接超时设置
            async with websockets.connect(
                config.WEBSOCKET_URL,
                ping_interval=20,
                ping_timeout=10,
                close_timeout=10
            ) as websocket:
                logger.info("WebSocket 连接成功")
                await self.subscribe_ticker(websocket)
                logger.info("已订阅 ticker 数据")
                await self.subscribe_orders(websocket)
                logger.info("已订阅订单数据")
                
                # 监听消息
                while True:
                    try:
                        message = await websocket.recv()
                        data = json.loads(message)
                        
                        if data.get("e") == "bookTicker":
                            await self.handle_ticker_update(message)
                        elif data.get("e") == "ORDER_TRADE_UPDATE":
                            await self.handle_order_update(message)
                            
                    except json.JSONDecodeError as e:
                        logger.error(f"WebSocket 消息解析失败: {e}")
                    except Exception as e:
                        logger.error(f"WebSocket 消息处理失败: {e}")
                        break
        except websockets.exceptions.ConnectionClosed as e:
            logger.warning(f"WebSocket 连接已关闭: {e}")
            raise
        except Exception as e:
            logger.error(f"WebSocket 连接失败: {e}")
            raise
    
    def get_recent_trades(self, hours: int = 1):
        """获取最近几小时的交易记录（供调度器使用）"""
        # 这里可以实现获取最近交易记录的逻辑
        # 目前返回空列表，实际使用时可以从交易所API获取
        return []
    
    async def run(self):
        """启动机器人"""
        # 在开始交易前，先下载历史数据并进行EMA+ADX计算
        logger.info("开始下载历史K线数据进行EMA+ADX计算...")
        try:
            # 下载足够的历史数据（至少200根K线用于EMA200计算）
            klines = self.exchange_interface.get_klines(timeframe='5m', limit=300)
            if len(klines) < 200:
                logger.error(f"历史数据不足，仅获取到 {len(klines)} 根K线，需要至少200根")
                raise ValueError("历史数据不足")
            
            # 提取价格数据
            closes = [float(kline['close']) for kline in klines]
            highs = [float(kline['high']) for kline in klines]
            lows = [float(kline['low']) for kline in klines]
            
            # 初始化信号模块的历史数据
            logger.info("初始化EMA+ADX信号模块历史数据...")
            for i, kline in enumerate(klines):
                data_point = {
                    'timestamp': kline['timestamp'],
                    'open': kline['open'],
                    'high': kline['high'],
                    'low': kline['low'],
                    'close': kline['close'],
                    'volume': kline['volume']
                }
                self.signal_module.update_data_buffer(data_point)
            
            # 获取当前信号状态
            signal_info = self.signal_module.calculate_signals()
            logger.info(f"EMA+ADX信号模块初始化完成，当前信号: {signal_info['signal_name']} (置信度: {signal_info['confidence']}%)")
            
            # 设置初始信号状态
            self.signal_module.current_signal = signal_info['signal']
            
        except Exception as e:
            logger.error(f"下载历史数据或初始化信号模块失败: {e}")
            logger.error("程序将继续运行，但EMA+ADX功能可能不准确")
        
        # 初始化时获取一次持仓数据
        long_pos, short_pos = self.exchange_interface.get_position()
        self.grid_core.long_position = long_pos
        self.grid_core.short_position = short_pos
        logger.info(f"初始化持仓: 多头 {long_pos} 张, 空头 {short_pos} 张")
        
        # 等待状态同步完成
        await asyncio.sleep(5)
        
        # 初始化时获取一次挂单状态
        self.grid_core.check_orders_status()
        logger.info(
            f"初始化挂单状态: 多头开仓={self.grid_core.buy_long_orders}, "
            f"多头止盈={self.grid_core.sell_long_orders}, "
            f"空头开仓={self.grid_core.sell_short_orders}, "
            f"空头止盈={self.grid_core.buy_short_orders}"
        )
        
        # 启动汇总功能调度器
        logger.info("启动网格交易汇总功能调度器...")
        grid_scheduler.start_scheduler()
        
        # 启动后台任务
        asyncio.create_task(self.keep_listen_key_alive())
        # asyncio.create_task(self.monitor_orders())  # 可选：启用订单监控
        
        # 主循环：WebSocket连接
        try:
            while True:
                try:
                    await self.connect_websocket()
                except Exception as e:
                    logger.error(f"WebSocket 连接失败: {e}")
                    await asyncio.sleep(5)  # 等待 5 秒后重试
        except KeyboardInterrupt:
            logger.info("接收到停止信号，正在关闭程序...")
        finally:
            # 停止调度器
            logger.info("停止网格交易汇总功能调度器...")
            grid_scheduler.stop_scheduler()

# ==================== 主程序 ====================
async def main():
    """主函数"""
    bot = GridTradingBot()
    await bot.run()

if __name__ == "__main__":
    asyncio.run(main())