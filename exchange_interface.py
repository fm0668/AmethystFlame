#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
交易所接口模块
包含所有与币安API交互的功能
"""

import ccxt
import uuid
import time
import logging
from config import config

logger = logging.getLogger(__name__)

class CustomGate(ccxt.binance):
    """自定义Gate交易所类，继承自ccxt.binance"""
    
    def __init__(self, config_dict):
        super().__init__(config_dict)
        self.options['defaultType'] = 'future'  # 设置为期货交易

class ExchangeInterface:
    """交易所接口类"""
    
    def __init__(self):
        self.exchange = None
        self.websocket_price = None  # WebSocket实时价格
        self.last_valid_price = None  # 最后有效价格
        self.last_price_update_time = 0  # 最后价格更新时间
        self.price_precision = None
        self.amount_precision = None
        self.min_order_amount = None
        self.listen_key = None
        
    def initialize_exchange(self):
        """初始化交易所连接"""
        try:
            exchange_config = {
                'apiKey': config.API_KEY,
                'secret': config.API_SECRET,
                'sandbox': False,  # 设置为 False 使用实盘
                'enableRateLimit': True,
                'options': {
                    'defaultType': 'future',  # 设置为期货交易
                }
            }
            
            self.exchange = CustomGate(exchange_config)
            logger.info("交易所连接初始化成功")
            
            # 设置杠杆倍数
            self.set_leverage()
            
            # 获取交易精度信息
            self._get_price_precision()
            
        except Exception as e:
            logger.error(f"交易所初始化失败: {e}")
            raise
    
    def _get_price_precision(self):
        """获取价格和数量精度"""
        try:
            markets = self.exchange.load_markets()
            symbol_info = markets.get(config.get_ccxt_symbol())
            
            if symbol_info:
                self.price_precision = symbol_info['precision']['price']
                self.amount_precision = symbol_info['precision']['amount']
                self.min_order_amount = symbol_info['limits']['amount']['min']
                
                logger.info(
                    f"价格精度: {self.price_precision}, 数量精度: {self.amount_precision}, 最小下单数量: {self.min_order_amount}")
            else:
                logger.error(f"无法获取 {config.get_ccxt_symbol()} 的市场信息")
                
        except Exception as e:
            logger.error(f"获取价格精度失败: {e}")
            raise
    
    def set_leverage(self, symbol=None, leverage=None):
        """设置杠杆倍数"""
        try:
            if symbol is None:
                symbol = config.get_ccxt_symbol()
            if leverage is None:
                leverage = config.LEVERAGE
                
            # 使用币安API设置杠杆
            params = {
                'symbol': symbol.replace('/', '').replace(':USDC', ''),
                'leverage': leverage
            }
            response = self.exchange.fapiPrivatePostLeverage(params)
            logger.info(f"成功设置杠杆倍数为 {leverage}x: {response}")
            return True
            
        except Exception as e:
            logger.error(f"设置杠杆失败: {e}")
            return False
    
    def generate_client_order_id(self):
        """生成唯一的客户端订单ID"""
        return str(uuid.uuid4())
    
    def check_and_enable_hedge_mode(self):
        """检查并启用双向持仓模式"""
        try:
            # 使用ccxt的fetch_position_mode方法检查持仓模式
            position_mode = self.exchange.fetch_position_mode(symbol=config.get_ccxt_symbol())
            if not position_mode['hedged']:
                logger.info("当前为单向持仓模式，正在切换为双向持仓模式...")
                # 启用双向持仓模式
                params = {'dualSidePosition': 'true'}
                self.exchange.fapiPrivatePostPositionSideDual(params)
                
                # 二次验证
                position_mode = self.exchange.fetch_position_mode(symbol=config.get_ccxt_symbol())
                if not position_mode['hedged']:
                    logger.error("启用双向持仓模式失败，请手动启用双向持仓模式后再运行程序。")
                    raise Exception("启用双向持仓模式失败，请手动启用双向持仓模式后再运行程序。")
                else:
                    logger.info("双向持仓模式已成功启用")
            else:
                logger.info("双向持仓模式已启用")
                
            return True
            
        except Exception as e:
            logger.error(f"检查/启用双向持仓模式失败: {e}")
            raise e  # 抛出异常，停止程序
    
    def get_listen_key(self):
        """获取listenKey用于WebSocket连接"""
        try:
            response = self.exchange.fapiPrivatePostListenKey()
            listen_key = response.get('listenKey')
            if not listen_key:
                raise ValueError("获取的 listenKey 为空")
            logger.info(f"成功获取 listenKey: {listen_key}")
            return listen_key
        except Exception as e:
            logger.error(f"获取listenKey失败: {e}")
            return None
    
    def keep_listen_key_alive(self, listen_key):
        """保持listenKey活跃"""
        try:
            self.exchange.fapiPrivatePutListenKey()
            logger.info("listenKey续期成功")
        except Exception as e:
            logger.error(f"listenKey续期失败: {e}")
    
    def get_position(self):
        """获取当前持仓"""
        try:
            params = {'type': 'future'}  # 永续合约
            positions = self.exchange.fetch_positions(params=params)
            
            long_position = 0
            short_position = 0
            
            for position in positions:
                if position['symbol'] == config.get_ccxt_symbol():
                    contracts = position.get('contracts', 0)
                    side = position.get('side', None)
                    
                    if side == 'long':
                        long_position = contracts
                    elif side == 'short':
                        short_position = abs(contracts)
            
            return long_position, short_position
            
        except Exception as e:
            logger.error(f"获取持仓失败: {e}")
            return 0, 0
    
    def fetch_open_orders(self, symbol=None):
        """获取未成交订单"""
        try:
            if symbol is None:
                symbol = config.get_ccxt_symbol()
            return self.exchange.fetch_open_orders(symbol=symbol)
        except Exception as e:
            logger.error(f"获取未成交订单失败: {e}")
            return []
    
    def cancel_order(self, order_id, symbol=None):
        """取消订单"""
        try:
            if symbol is None:
                symbol = config.get_ccxt_symbol()
            self.exchange.cancel_order(order_id, symbol)
            logger.info(f"撤销订单成功, 订单ID: {order_id}")
        except ccxt.BaseError as e:
            logger.error(f"撤单失败: {e}")
    
    def place_order(self, side, price, quantity, is_reduce_only=False, position_side=None, order_type='limit'):
        """下单函数"""
        try:
            # 修正价格精度
            if price is not None:
                price = round(price, self.price_precision)
            
            # 修正数量精度并确保不低于最小下单数量
            quantity = round(quantity, self.amount_precision)
            quantity = max(quantity, self.min_order_amount)
            
            params = {
                'newClientOrderId': self.generate_client_order_id(),
                'reduce_only': is_reduce_only,
            }
            
            if position_side is not None:
                params['positionSide'] = position_side.upper()
            
            if order_type == 'market':
                order = self.exchange.create_order(
                    config.get_ccxt_symbol(), 'market', side, quantity, params=params
                )
            else:
                if price is None:
                    logger.error("限价单必须提供 price 参数")
                    return None
                order = self.exchange.create_order(
                    config.get_ccxt_symbol(), 'limit', side, quantity, price, params
                )
            
            # 记录交易到汇总模块（仅在订单创建成功时）
            if order and order.get('id'):
                try:
                    from grid_scheduler import add_trade_record
                    
                    # 确定网格类型
                    grid_type = 'long' if position_side == 'LONG' else 'short'
                    
                    # 计算预期盈利（简化计算，实际盈利在成交时计算）
                    estimated_profit = 0.0
                    if order_type == 'limit' and price:
                        # 对于限价单，预估盈利为0（实际盈利在成交时计算）
                        estimated_profit = 0.0
                    
                    # 添加交易记录
                    add_trade_record(
                        trade_type=side,
                        grid_type=grid_type,
                        price=price if price else 0.0,
                        quantity=quantity,
                        profit=estimated_profit,
                        grid_level=0,  # 网格层级，可以后续优化
                        order_id=str(order['id'])
                    )
                    
                except Exception as e:
                    logger.warning(f"记录交易到汇总模块失败: {e}")
            
            return order
            
        except ccxt.BaseError as e:
            logger.error(f"下单报错: {e}")
            return None
    
    def get_klines(self, symbol=None, timeframe='5m', limit=200):
        """获取K线数据"""
        try:
            if symbol is None:
                symbol = config.get_ccxt_symbol()
            
            # 使用ccxt获取K线数据
            ohlcv = self.exchange.fetch_ohlcv(symbol, timeframe, limit=limit)
            
            # 转换为更易用的格式
            klines = []
            for candle in ohlcv:
                klines.append({
                    'timestamp': candle[0],
                    'open': candle[1],
                    'high': candle[2],
                    'low': candle[3],
                    'close': candle[4],
                    'volume': candle[5]
                })
            
            logger.info(f"成功获取 {len(klines)} 根K线数据")
            return klines
            
        except Exception as e:
            logger.error(f"获取K线数据失败: {e}")
            return []
    
    def get_ticker(self, symbol=None):
        """获取ticker价格信息 - 混合策略"""
        try:
            # 优先使用WebSocket实时价格
            if self.websocket_price and self._validate_price(self.websocket_price):
                logger.debug(f"使用WebSocket价格: {self.websocket_price}")
                return {'price': self.websocket_price}
            
            # 备用REST API
            if symbol is None:
                symbol = config.get_ccxt_symbol()
            
            # 使用ccxt获取ticker数据
            ticker = self.exchange.fetch_ticker(symbol)
            
            # 验证ticker数据的有效性
            if not ticker or 'last' not in ticker:
                logger.error(f"获取到无效的ticker数据: {ticker}")
                return {'price': self.last_valid_price}  # 返回最后有效价格
            
            price = ticker.get('last')  # 最新成交价
            if not self._validate_price(price):
                logger.error(f"获取到无效的价格: {price}")
                return {'price': self.last_valid_price}  # 返回最后有效价格
            
            # 更新价格缓存
            self.update_price_cache(price)
            logger.debug(f"成功获取REST API价格: {price}")
            return {'price': price}
            
        except Exception as e:
            logger.error(f"获取ticker失败: {e}")
            return {'price': self.last_valid_price}  # 返回最后有效价格

    def _validate_price(self, price):
        """简化的价格验证"""
        if price is None or price <= 0:
            return False
        
        # 只做基本的合理性检查，避免过度验证
        if self.last_valid_price:
            # 价格变动超过10%才认为异常
            change_ratio = abs(price - self.last_valid_price) / self.last_valid_price
            if change_ratio > 0.1:
                logger.warning(f"价格变动异常: {self.last_valid_price} -> {price}")
                return False
        
        return True

    def update_price_cache(self, price):
        """更新价格缓存"""
        if self._validate_price(price):
            self.last_valid_price = price
            self.last_price_update_time = time.time()

    def update_websocket_price(self, price):
        """更新WebSocket价格"""
        if self._validate_price(price):
            self.websocket_price = price
            self.update_price_cache(price)

    def place_take_profit_order(self, side, price, quantity):
        """挂止盈单"""
        try:
            # 检查是否已有相同价格的挂单
            orders = self.fetch_open_orders()
            for order in orders:
                if (
                    order['info'].get('positionSide') == side.upper()
                    and float(order['price']) == price
                    and order['side'] == ('sell' if side == 'long' else 'buy')
                ):
                    logger.info(f"已存在相同价格的 {side} 止盈单，跳过挂单")
                    return
            
            # 修正价格精度
            price = round(price, self.price_precision)
            
            # 修正数量精度并确保不低于最小下单数量
            quantity = round(quantity, self.amount_precision)
            quantity = max(quantity, self.min_order_amount)
            
            params = {
                'newClientOrderId': self.generate_client_order_id(),
                'reduce_only': True,
                'positionSide': side.upper()
            }
            
            if side == 'long':
                order = self.exchange.create_order(
                    config.get_ccxt_symbol(), 'limit', 'sell', quantity, price, params
                )
                logger.info(f"成功挂 long 止盈单: 卖出 {quantity} @ {price}")
            elif side == 'short':
                order = self.exchange.create_order(
                    config.get_ccxt_symbol(), 'limit', 'buy', quantity, price, params
                )
                logger.info(f"成功挂 short 止盈单: 买入 {quantity} @ {price}")
            
            return order
            
        except ccxt.BaseError as e:
            logger.error(f"挂止盈单失败: {e}")
            return None