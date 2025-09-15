#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
网格交易机器人配置模块
集中管理所有配置参数
"""

import os
from dotenv import load_dotenv

# 加载环境变量
load_dotenv()

class Config:
    """配置类"""
    
    def __init__(self):
        # ==================== API 配置 ====================
        self.API_KEY = os.getenv('API_KEY', '')
        self.API_SECRET = os.getenv('API_SECRET', '')
        
        # ==================== 交易配置 ====================
        self.COIN_NAME = "XRP"  # 币种名称
        self.CONTRACT_TYPE = "USDC"  # 合约类型：USDT 或 USDC
        self.GRID_SPACING = 0.001  # 网格间距（0.1%）
        self.INITIAL_QUANTITY = 3  # 初始下单数量
        self.LEVERAGE = 15  # 杠杆倍数
        
        # ==================== 风控配置 ====================
        self.POSITION_THRESHOLD = 500  # 持仓阈值，超过此值进入保守模式
        self.POSITION_LIMIT = 200  # 持仓数量阈值
        self.SYNC_TIME = 10  # 同步时间（秒）
        self.ORDER_FIRST_TIME = 10  # 首次挂单间隔时间（秒）
        
        # ==================== WebSocket 配置 ====================
        self.WEBSOCKET_URL = "wss://fstream.binance.com/ws"
        
        # ==================== 日志配置 ====================
        self.LOG_LEVEL = "INFO"
        self.LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"
        self.LOG_FILE = "grid_trading.log"
        
    def get_ccxt_symbol(self):
        """获取CCXT格式的交易对符号"""
        return f"{self.COIN_NAME}/{self.CONTRACT_TYPE}:{self.CONTRACT_TYPE}"
    
    def print_config(self):
        """打印配置信息"""
        print("=" * 50)
        print("网格交易机器人配置信息:")
        print(f"币种: {self.COIN_NAME}")
        print(f"合约类型: {self.CONTRACT_TYPE}")
        print(f"交易对: {self.get_ccxt_symbol()}")
        print(f"网格间距: {self.GRID_SPACING * 100}%")
        print(f"初始数量: {self.INITIAL_QUANTITY}")
        print(f"杠杆倍数: {self.LEVERAGE}x")
        print(f"持仓阈值: {self.POSITION_THRESHOLD}")
        print("=" * 50)

# 创建全局配置实例
config = Config()