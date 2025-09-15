#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
网格交易数据汇总模块
功能：统计和汇总网格交易的各项关键指标
作者：AmethystFlame
版本：v2.2
"""

import json
import os
from datetime import datetime, timedelta
from typing import Dict, List, Optional, Tuple
import numpy as np
from dataclasses import dataclass, asdict
import logging

@dataclass
class GridTradeRecord:
    """网格交易记录"""
    timestamp: str
    trade_type: str  # 'buy' or 'sell'
    grid_type: str   # 'long' or 'short'
    price: float
    quantity: float
    profit: float
    grid_level: int
    order_id: str

@dataclass
class DailySummary:
    """每日汇总数据"""
    date: str
    # 盈亏相关
    daily_pnl: float
    total_pnl: float
    daily_return_rate: float
    total_return_rate: float
    
    # 交易次数统计
    total_trades: int
    daily_trades: int
    long_trades: int
    short_trades: int
    daily_long_trades: int
    daily_short_trades: int
    
    # 持仓统计
    total_position: float
    long_position: float
    short_position: float
    
    # 风险指标
    sharpe_ratio: float
    max_drawdown: float
    win_rate: float
    
    # 网格状态
    active_grids: int
    grid_spacing: float
    current_price: float
    
    # 资金使用
    total_capital: float
    used_capital: float
    available_capital: float

class GridSummaryModule:
    """网格交易汇总模块"""
    
    def __init__(self, summary_dir: str = "grid_summary_reports"):
        self.summary_dir = summary_dir
        self.trade_records: List[GridTradeRecord] = []
        self.daily_summaries: Dict[str, DailySummary] = {}
        self.logger = self._setup_logger()
        
        # 确保汇总目录存在
        os.makedirs(self.summary_dir, exist_ok=True)
        
        # 加载历史数据
        self._load_historical_data()
    
    def _setup_logger(self) -> logging.Logger:
        """设置日志记录器"""
        logger = logging.getLogger('GridSummary')
        logger.setLevel(logging.INFO)
        
        if not logger.handlers:
            handler = logging.FileHandler(
                os.path.join(self.summary_dir, 'summary.log'),
                encoding='utf-8'
            )
            formatter = logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
            )
            handler.setFormatter(formatter)
            logger.addHandler(handler)
        
        return logger
    
    def add_trade_record(self, trade_record: GridTradeRecord):
        """添加交易记录"""
        self.trade_records.append(trade_record)
        self.logger.info(f"添加交易记录: {trade_record.trade_type} {trade_record.quantity} @ {trade_record.price}")
    
    def calculate_sharpe_ratio(self, returns: List[float], risk_free_rate: float = 0.02) -> float:
        """计算夏普比率"""
        if len(returns) < 2:
            return 0.0
        
        returns_array = np.array(returns)
        excess_returns = returns_array - risk_free_rate / 365  # 日化无风险利率
        
        if np.std(excess_returns) == 0:
            return 0.0
        
        return np.mean(excess_returns) / np.std(excess_returns) * np.sqrt(365)
    
    def calculate_max_drawdown(self, pnl_series: List[float]) -> float:
        """计算最大回撤"""
        if len(pnl_series) < 2:
            return 0.0
        
        cumulative_pnl = np.cumsum(pnl_series)
        running_max = np.maximum.accumulate(cumulative_pnl)
        drawdown = (cumulative_pnl - running_max) / np.maximum(running_max, 1)
        
        return abs(np.min(drawdown))
    
    def calculate_win_rate(self, trades: List[GridTradeRecord]) -> float:
        """计算胜率"""
        if not trades:
            return 0.0
        
        profitable_trades = sum(1 for trade in trades if trade.profit > 0)
        return profitable_trades / len(trades)
    
    def generate_daily_summary(self, target_date: str, current_price: float, 
                             total_capital: float, grid_config: Dict) -> DailySummary:
        """生成指定日期的汇总报告"""
        date_obj = datetime.strptime(target_date, '%Y-%m-%d')
        
        # 筛选当日交易记录
        daily_trades = [
            trade for trade in self.trade_records
            if trade.timestamp.startswith(target_date)
        ]
        
        # 筛选历史所有交易记录（到目标日期为止）
        all_trades = [
            trade for trade in self.trade_records
            if datetime.strptime(trade.timestamp[:10], '%Y-%m-%d') <= date_obj
        ]
        
        # 计算盈亏
        daily_pnl = sum(trade.profit for trade in daily_trades)
        total_pnl = sum(trade.profit for trade in all_trades)
        
        # 计算收益率
        daily_return_rate = daily_pnl / total_capital if total_capital > 0 else 0
        total_return_rate = total_pnl / total_capital if total_capital > 0 else 0
        
        # 统计交易次数
        daily_long_trades = sum(1 for trade in daily_trades if trade.grid_type == 'long')
        daily_short_trades = sum(1 for trade in daily_trades if trade.grid_type == 'short')
        long_trades = sum(1 for trade in all_trades if trade.grid_type == 'long')
        short_trades = sum(1 for trade in all_trades if trade.grid_type == 'short')
        
        # 计算持仓（简化计算，实际应根据具体策略调整）
        long_position = sum(trade.quantity for trade in all_trades 
                          if trade.grid_type == 'long' and trade.trade_type == 'buy') - \
                       sum(trade.quantity for trade in all_trades 
                          if trade.grid_type == 'long' and trade.trade_type == 'sell')
        
        short_position = sum(trade.quantity for trade in all_trades 
                           if trade.grid_type == 'short' and trade.trade_type == 'sell') - \
                        sum(trade.quantity for trade in all_trades 
                           if trade.grid_type == 'short' and trade.trade_type == 'buy')
        
        total_position = abs(long_position) + abs(short_position)
        
        # 计算风险指标
        daily_returns = []
        for i in range(30):  # 最近30天的收益率
            check_date = (date_obj - timedelta(days=i)).strftime('%Y-%m-%d')
            day_trades = [t for t in all_trades if t.timestamp.startswith(check_date)]
            day_pnl = sum(t.profit for t in day_trades)
            daily_returns.append(day_pnl / total_capital if total_capital > 0 else 0)
        
        sharpe_ratio = self.calculate_sharpe_ratio(daily_returns)
        
        # 计算最大回撤
        pnl_series = []
        for i in range(len(all_trades)):
            pnl_series.append(sum(t.profit for t in all_trades[:i+1]))
        max_drawdown = self.calculate_max_drawdown(pnl_series)
        
        # 计算胜率
        win_rate = self.calculate_win_rate(all_trades)
        
        # 资金使用情况
        used_capital = total_position * current_price
        available_capital = total_capital - used_capital
        
        return DailySummary(
            date=target_date,
            daily_pnl=daily_pnl,
            total_pnl=total_pnl,
            daily_return_rate=daily_return_rate,
            total_return_rate=total_return_rate,
            total_trades=len(all_trades),
            daily_trades=len(daily_trades),
            long_trades=long_trades,
            short_trades=short_trades,
            daily_long_trades=daily_long_trades,
            daily_short_trades=daily_short_trades,
            total_position=total_position,
            long_position=long_position,
            short_position=short_position,
            sharpe_ratio=sharpe_ratio,
            max_drawdown=max_drawdown,
            win_rate=win_rate,
            active_grids=grid_config.get('active_grids', 0),
            grid_spacing=grid_config.get('grid_spacing', 0),
            current_price=current_price,
            total_capital=total_capital,
            used_capital=used_capital,
            available_capital=available_capital
        )
    
    def save_daily_summary(self, summary: DailySummary):
        """保存每日汇总报告"""
        # 保存为JSON格式
        json_file = os.path.join(self.summary_dir, f"summary_{summary.date}.json")
        with open(json_file, 'w', encoding='utf-8') as f:
            json.dump(asdict(summary), f, ensure_ascii=False, indent=2)
        
        # 保存为可读格式
        txt_file = os.path.join(self.summary_dir, f"summary_{summary.date}.txt")
        with open(txt_file, 'w', encoding='utf-8') as f:
            f.write(self._format_summary_report(summary))
        
        # 更新内存中的汇总数据
        self.daily_summaries[summary.date] = summary
        
        self.logger.info(f"保存每日汇总报告: {summary.date}")
    
    def _format_summary_report(self, summary: DailySummary) -> str:
        """格式化汇总报告为可读文本"""
        report = f"""
==========================================
网格交易策略每日汇总报告
日期: {summary.date}
==========================================

📊 盈亏情况
├─ 当日盈亏: {summary.daily_pnl:,.2f} USDT
├─ 总盈亏: {summary.total_pnl:,.2f} USDT
├─ 当日收益率: {summary.daily_return_rate:.4%}
└─ 总收益率: {summary.total_return_rate:.4%}

📈 交易统计
├─ 总交易次数: {summary.total_trades}
├─ 当日交易次数: {summary.daily_trades}
├─ 做多交易次数: {summary.long_trades} (当日: {summary.daily_long_trades})
└─ 做空交易次数: {summary.short_trades} (当日: {summary.daily_short_trades})

💰 持仓情况
├─ 总持仓量: {summary.total_position:.4f}
├─ 做多持仓: {summary.long_position:.4f}
└─ 做空持仓: {summary.short_position:.4f}

⚡ 风险指标
├─ 夏普比率: {summary.sharpe_ratio:.4f}
├─ 最大回撤: {summary.max_drawdown:.4%}
└─ 胜率: {summary.win_rate:.4%}

🔧 网格状态
├─ 活跃网格数: {summary.active_grids}
├─ 网格间距: {summary.grid_spacing:.4f}
└─ 当前价格: {summary.current_price:.4f}

💵 资金使用
├─ 总资金: {summary.total_capital:,.2f} USDT
├─ 已用资金: {summary.used_capital:,.2f} USDT
└─ 可用资金: {summary.available_capital:,.2f} USDT

==========================================
报告生成时间: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
==========================================
"""
        return report
    
    def cleanup_old_reports(self, days_to_keep: int = 30):
        """清理超过指定天数的旧报告"""
        cutoff_date = datetime.now() - timedelta(days=days_to_keep)
        
        for filename in os.listdir(self.summary_dir):
            if filename.startswith('summary_') and (filename.endswith('.json') or filename.endswith('.txt')):
                try:
                    # 从文件名提取日期
                    date_str = filename.split('_')[1].split('.')[0]
                    file_date = datetime.strptime(date_str, '%Y-%m-%d')
                    
                    if file_date < cutoff_date:
                        file_path = os.path.join(self.summary_dir, filename)
                        os.remove(file_path)
                        self.logger.info(f"删除过期报告: {filename}")
                        
                        # 从内存中移除
                        if date_str in self.daily_summaries:
                            del self.daily_summaries[date_str]
                            
                except (ValueError, IndexError) as e:
                    self.logger.warning(f"无法解析文件日期: {filename}, 错误: {e}")
    
    def _load_historical_data(self):
        """加载历史汇总数据"""
        try:
            for filename in os.listdir(self.summary_dir):
                if filename.startswith('summary_') and filename.endswith('.json'):
                    date_str = filename.split('_')[1].split('.')[0]
                    file_path = os.path.join(self.summary_dir, filename)
                    
                    with open(file_path, 'r', encoding='utf-8') as f:
                        data = json.load(f)
                        self.daily_summaries[date_str] = DailySummary(**data)
                        
            self.logger.info(f"加载历史汇总数据: {len(self.daily_summaries)} 条记录")
        except Exception as e:
            self.logger.error(f"加载历史数据失败: {e}")
    
    def get_summary_by_date(self, date: str) -> Optional[DailySummary]:
        """获取指定日期的汇总数据"""
        return self.daily_summaries.get(date)
    
    def get_recent_summaries(self, days: int = 7) -> List[DailySummary]:
        """获取最近几天的汇总数据"""
        end_date = datetime.now()
        summaries = []
        
        for i in range(days):
            date = (end_date - timedelta(days=i)).strftime('%Y-%m-%d')
            if date in self.daily_summaries:
                summaries.append(self.daily_summaries[date])
        
        return summaries

# 全局汇总模块实例
grid_summary = GridSummaryModule()