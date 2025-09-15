#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
EMA+ADX信号生成模块

用于网格策略的趋势信号检测和网格间距动态调整
集成到网格策略中，根据强趋势信号调整网格参数
"""

import pandas as pd
import numpy as np
import warnings
from datetime import datetime
import logging

warnings.filterwarnings('ignore')

class EMAAdxSignalModule:
    """
    EMA+ADX信号生成模块
    用于检测强趋势信号并为网格策略提供动态调整建议
    """
    
    def __init__(self, ema_short=20, ema_medium=50, ema_long=200, adx_period=14, adx_threshold=25):
        """
        初始化信号模块
        
        Args:
            ema_short: 短期EMA周期，默认20
            ema_medium: 中期EMA周期，默认50
            ema_long: 长期EMA周期，默认200
            adx_period: ADX计算周期，默认14
            adx_threshold: ADX强趋势阈值，默认25
        """
        self.ema_short = ema_short
        self.ema_medium = ema_medium
        self.ema_long = ema_long
        self.adx_period = adx_period
        self.adx_threshold = adx_threshold
        
        # 信号状态
        self.current_signal = 0  # 0: 震荡, 1: 强多, -1: 强空
        self.signal_start_time = None
        self.last_update_time = None
        
        # 历史数据缓存
        self.data_buffer = pd.DataFrame()
        self.buffer_size = ema_long + 50  # 确保有足够数据计算指标，但不要过大
        
        logging.info(f"EMA+ADX信号模块初始化完成 - EMA({ema_short},{ema_medium},{ema_long}) ADX({adx_period},{adx_threshold})")
    
    def calculate_ema(self, data, period):
        """计算指数移动平均线"""
        return data.ewm(span=period, adjust=False).mean()
    
    def calculate_adx(self, high, low, close, period=14):
        """计算ADX指标 - 使用与Pine Script相同的Wilder平滑方法"""
        # 计算True Range (TR)
        high_low = high - low
        high_close = np.abs(high - close.shift(1))
        low_close = np.abs(low - close.shift(1))
        tr = np.maximum(high_low, np.maximum(high_close, low_close))
        
        # 计算方向移动 (DM)
        plus_dm = high.diff()
        minus_dm = -low.diff()
        
        # 只保留正值，负值设为0
        plus_dm = pd.Series(np.where(plus_dm > 0, plus_dm, 0), index=plus_dm.index)
        minus_dm = pd.Series(np.where(minus_dm > 0, minus_dm, 0), index=minus_dm.index)
        
        # 当+DM和-DM同时为正时，只保留较大的那个
        plus_dm = pd.Series(np.where((plus_dm > 0) & (minus_dm > 0) & (plus_dm <= minus_dm), 0, plus_dm), index=plus_dm.index)
        minus_dm = pd.Series(np.where((plus_dm > 0) & (minus_dm > 0) & (minus_dm <= plus_dm), 0, minus_dm), index=minus_dm.index)
        
        # 使用Wilder平滑方法计算平滑的TR和DM（与Pine Script一致）
        smoothed_tr = pd.Series(index=tr.index, dtype=float)
        smoothed_plus_dm = pd.Series(index=plus_dm.index, dtype=float)
        smoothed_minus_dm = pd.Series(index=minus_dm.index, dtype=float)
        
        # 初始化第一个period的值为简单平均
        smoothed_tr.iloc[period-1] = tr.iloc[:period].mean()
        smoothed_plus_dm.iloc[period-1] = plus_dm[:period].mean()
        smoothed_minus_dm.iloc[period-1] = minus_dm[:period].mean()
        
        # 使用Wilder平滑公式：新值 = 前值 - (前值/period) + 当前值
        for i in range(period, len(tr)):
            smoothed_tr.iloc[i] = smoothed_tr.iloc[i-1] - (smoothed_tr.iloc[i-1] / period) + tr.iloc[i]
            smoothed_plus_dm.iloc[i] = smoothed_plus_dm.iloc[i-1] - (smoothed_plus_dm.iloc[i-1] / period) + plus_dm.iloc[i]
            smoothed_minus_dm.iloc[i] = smoothed_minus_dm.iloc[i-1] - (smoothed_minus_dm.iloc[i-1] / period) + minus_dm.iloc[i]
        
        # 计算DI+ 和 DI-
        plus_di = 100 * (smoothed_plus_dm / smoothed_tr)
        minus_di = 100 * (smoothed_minus_dm / smoothed_tr)
        
        # 计算DX
        dx = 100 * np.abs(plus_di - minus_di) / (plus_di + minus_di)
        
        # 计算ADX - 使用简单移动平均对DX进行平滑
        adx = dx.rolling(window=period).mean()
        
        return adx, plus_di, minus_di
    
    def update_data_buffer(self, new_data):
        """
        更新数据缓存
        
        Args:
            new_data: 新的K线数据，包含timestamp, open, high, low, close, volume
        """
        # 将新数据添加到缓存
        if isinstance(new_data, dict):
            new_df = pd.DataFrame([new_data])
            if 'timestamp' in new_df.columns:
                new_df.set_index('timestamp', inplace=True)
        else:
            new_df = new_data.copy()
        
        # 合并数据
        if self.data_buffer.empty:
            self.data_buffer = new_df
        else:
            self.data_buffer = pd.concat([self.data_buffer, new_df])
            # 保持缓存大小
            if len(self.data_buffer) > self.buffer_size:
                self.data_buffer = self.data_buffer.tail(self.buffer_size)
        
        # 确保数据类型正确
        for col in ['open', 'high', 'low', 'close', 'volume']:
            if col in self.data_buffer.columns:
                self.data_buffer[col] = pd.to_numeric(self.data_buffer[col], errors='coerce')
    
    def calculate_signals(self, df=None):
        """
        计算当前的趋势信号
        
        Args:
            df: 可选的数据框，如果不提供则使用内部缓存
            
        Returns:
            dict: 包含信号信息的字典
        """
        if df is None:
            df = self.data_buffer.copy()
        
        if len(df) < self.buffer_size:
            return {
                'signal': 0,
                'signal_name': 'Insufficient Data',
                'confidence': 0,
                'adx_value': 0,
                'ema_alignment': False
            }
        
        # 计算EMA指标
        df['ema_20'] = self.calculate_ema(df['close'], self.ema_short)
        df['ema_50'] = self.calculate_ema(df['close'], self.ema_medium)
        df['ema_200'] = self.calculate_ema(df['close'], self.ema_long)
        
        # 计算ADX指标
        df['adx'], df['plus_di'], df['minus_di'] = self.calculate_adx(
            df['high'], df['low'], df['close'], self.adx_period
        )
        
        # EMA20方向判断
        df['ema20_direction'] = df['ema_20'].diff()
        df['ema20_rising'] = df['ema20_direction'] > 0
        df['ema20_declining'] = df['ema20_direction'] < 0
        
        # 趋势状态判断
        df['market_above_200'] = df['close'] > df['ema_200']
        df['market_below_200'] = df['close'] < df['ema_200']
        df['ema_bullish_order'] = (df['ema_20'] > df['ema_50']) & (df['ema_50'] > df['ema_200'])
        df['ema_bearish_order'] = (df['ema_20'] < df['ema_50']) & (df['ema_50'] < df['ema_200'])
        df['strong_trend'] = df['adx'] > self.adx_threshold
        
        # 策略状态定义（加入EMA20方向过滤）
        df['strong_uptrend'] = (
            df['market_above_200'] & 
            df['ema_bullish_order'] & 
            df['strong_trend'] &
            ~df['ema20_declining']  # EMA20不能向下
        )
        
        df['strong_downtrend'] = (
            df['market_below_200'] & 
            df['ema_bearish_order'] & 
            df['strong_trend'] &
            ~df['ema20_rising']     # EMA20不能向上
        )
        
        # 生成交易信号
        signal = 0  # 默认震荡
        if df['strong_uptrend'].iloc[-1]:
            signal = 1  # 强多
        elif df['strong_downtrend'].iloc[-1]:
            signal = -1  # 强空
        
        # 信号名称映射
        signal_names = {0: 'Ranging/Weak', 1: 'Strong Uptrend', -1: 'Strong Downtrend'}
        
        # 计算信号置信度（基于ADX强度）
        current_adx = df['adx'].iloc[-1] if not pd.isna(df['adx'].iloc[-1]) else 0
        confidence = min(100, max(0, (current_adx - self.adx_threshold) / self.adx_threshold * 100)) if signal != 0 else 0
        
        return {
            'signal': signal,
            'signal_name': signal_names[signal],
            'confidence': round(confidence, 2),
            'adx_value': round(current_adx, 2),
            'ema_alignment': df['ema_bullish_order'].iloc[-1] if signal == 1 else df['ema_bearish_order'].iloc[-1] if signal == -1 else False,
            'ema_20': round(df['ema_20'].iloc[-1], 4),
            'ema_50': round(df['ema_50'].iloc[-1], 4),
            'ema_200': round(df['ema_200'].iloc[-1], 4),
            'plus_di': round(df['plus_di'].iloc[-1], 2) if not pd.isna(df['plus_di'].iloc[-1]) else 0,
            'minus_di': round(df['minus_di'].iloc[-1], 2) if not pd.isna(df['minus_di'].iloc[-1]) else 0
        }
    
    def update_signal_state(self, new_data):
        """
        更新信号状态（用于实时监控）
        
        Args:
            new_data: 新的K线数据
            
        Returns:
            dict: 信号更新信息
        """
        # 更新数据缓存
        self.update_data_buffer(new_data)
        
        # 计算当前信号
        signal_info = self.calculate_signals()
        new_signal = signal_info['signal']
        
        # 检查信号变化
        signal_changed = False
        if new_signal != self.current_signal:
            signal_changed = True
            self.current_signal = new_signal
            self.signal_start_time = datetime.now()
            
            logging.info(f"信号变化: {signal_info['signal_name']} (置信度: {signal_info['confidence']}%, ADX: {signal_info['adx_value']})")
        
        self.last_update_time = datetime.now()
        
        return {
            'signal_changed': signal_changed,
            'current_signal': self.current_signal,
            'signal_info': signal_info,
            'signal_duration': (self.last_update_time - self.signal_start_time).total_seconds() / 3600 if self.signal_start_time else 0
        }
    
    def get_grid_adjustment_recommendation(self):
        """
        获取网格调整建议
        
        Returns:
            dict: 网格调整建议
        """
        if self.current_signal == 1:  # 强多趋势
            return {
                'adjust_type': 'uptrend',
                'long_grid_spacing_multiplier': 1.0,  # 做多网格间距不变
                'short_grid_spacing_multiplier': 2.0,  # 做空网格补仓间距扩大2倍
                'long_profit_spacing_multiplier': 1.0,  # 做多止盈间距不变
                'short_profit_spacing_multiplier': 2.0,  # 做空止盈间距扩大2倍
                'recommendation': '上涨信号：扩宽做空网格补仓间距和止盈间距，降低做空频率'
            }
        elif self.current_signal == -1:  # 强空趋势
            return {
                'adjust_type': 'downtrend',
                'long_grid_spacing_multiplier': 2.0,  # 做多网格补仓间距扩大2倍
                'short_grid_spacing_multiplier': 1.0,  # 做空网格间距不变
                'long_profit_spacing_multiplier': 2.0,  # 做多止盈间距扩大2倍
                'short_profit_spacing_multiplier': 1.0,  # 做空止盈间距不变
                'recommendation': '下跌信号：扩宽做多网格补仓间距和止盈间距，降低做多频率'
            }
        else:  # 震荡或弱趋势
            return {
                'adjust_type': 'ranging',
                'long_grid_spacing_multiplier': 1.0,  # 所有间距保持原始设置
                'short_grid_spacing_multiplier': 1.0,
                'long_profit_spacing_multiplier': 1.0,
                'short_profit_spacing_multiplier': 1.0,
                'recommendation': '震荡行情：保持原始网格设置'
            }
    
    def get_status_summary(self):
        """
        获取模块状态摘要
        
        Returns:
            dict: 状态摘要信息
        """
        signal_names = {0: '震荡/弱趋势', 1: '强多趋势', -1: '强空趋势'}
        
        return {
            'module_name': 'EMA+ADX信号模块',
            'current_signal': self.current_signal,
            'signal_name': signal_names.get(self.current_signal, '未知'),
            'signal_start_time': self.signal_start_time.strftime('%Y-%m-%d %H:%M:%S') if self.signal_start_time else None,
            'last_update_time': self.last_update_time.strftime('%Y-%m-%d %H:%M:%S') if self.last_update_time else None,
            'data_buffer_size': len(self.data_buffer),
            'parameters': {
                'ema_short': self.ema_short,
                'ema_medium': self.ema_medium,
                'ema_long': self.ema_long,
                'adx_period': self.adx_period,
                'adx_threshold': self.adx_threshold
            }
        }

# 使用示例
if __name__ == "__main__":
    # 创建信号模块实例
    signal_module = EMAAdxSignalModule()
    
    # 模拟数据更新
    sample_data = {
        'timestamp': datetime.now(),
        'open': 1.0000,
        'high': 1.0050,
        'low': 0.9950,
        'close': 1.0025,
        'volume': 1000000
    }
    
    # 更新信号状态
    result = signal_module.update_signal_state(sample_data)
    print(f"信号更新结果: {result}")
    
    # 获取网格调整建议
    adjustment = signal_module.get_grid_adjustment_recommendation()
    print(f"网格调整建议: {adjustment}")
    
    # 获取状态摘要
    status = signal_module.get_status_summary()
    print(f"模块状态: {status}")