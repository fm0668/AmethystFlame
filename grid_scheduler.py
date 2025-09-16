#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
网格交易定时任务调度器
功能：管理网格交易系统的定时任务，包括每日汇总、数据清理等
作者：AmethystFlame
版本：v5.1
"""

import schedule
import time
import threading
from datetime import datetime, timedelta
import logging
from typing import Callable, Optional
from grid_summary_module import grid_summary, GridTradeRecord

class GridScheduler:
    """网格交易定时任务调度器"""
    
    def __init__(self):
        self.logger = self._setup_logger()
        self.is_running = False
        self.scheduler_thread: Optional[threading.Thread] = None
        self.grid_strategy = None  # 将在集成时设置
        
    def _setup_logger(self) -> logging.Logger:
        """设置日志记录器"""
        logger = logging.getLogger('GridScheduler')
        logger.setLevel(logging.INFO)
        
        if not logger.handlers:
            handler = logging.FileHandler(
                'grid_summary_reports/scheduler.log',
                encoding='utf-8'
            )
            formatter = logging.Formatter(
                '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
            )
            handler.setFormatter(formatter)
            logger.addHandler(handler)
        
        return logger
    
    def set_grid_strategy(self, strategy):
        """设置网格策略实例"""
        self.grid_strategy = strategy
        self.logger.info("网格策略实例已设置")
    
    def daily_summary_task(self):
        """每日汇总任务 - 在每天0点执行"""
        try:
            yesterday = (datetime.now() - timedelta(days=1)).strftime('%Y-%m-%d')
            self.logger.info(f"开始执行每日汇总任务: {yesterday}")
            
            if not self.grid_strategy:
                self.logger.error("网格策略实例未设置，无法执行汇总任务")
                return
            
            # 获取当前价格和网格配置
            try:
                current_price = self._get_current_price()
            except ValueError as e:
                self.logger.error(f"获取当前价格失败，跳过汇总任务: {e}")
                return
                
            total_capital = self._get_total_capital()
            grid_config = self._get_grid_config()
            
            # 生成每日汇总
            summary = grid_summary.generate_daily_summary(
                target_date=yesterday,
                current_price=current_price,
                total_capital=total_capital,
                grid_config=grid_config
            )
            
            # 保存汇总报告
            grid_summary.save_daily_summary(summary)
            
            self.logger.info(f"每日汇总任务完成: {yesterday}")
            
        except Exception as e:
            self.logger.error(f"每日汇总任务执行失败: {e}")
    
    def weekly_cleanup_task(self):
        """每周清理任务 - 清理超过30天的旧报告"""
        try:
            self.logger.info("开始执行每周清理任务")
            grid_summary.cleanup_old_reports(days_to_keep=30)
            self.logger.info("每周清理任务完成")
            
        except Exception as e:
            self.logger.error(f"每周清理任务执行失败: {e}")
    
    def hourly_backup_task(self):
        """每小时备份任务 - 备份当前交易数据"""
        try:
            current_time = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
            
            # 如果有新的交易记录，进行备份
            if hasattr(self.grid_strategy, 'get_recent_trades'):
                recent_trades = self.grid_strategy.get_recent_trades(hours=1)
                if recent_trades:
                    self.logger.info(f"备份 {len(recent_trades)} 条交易记录 - {current_time}")
            
        except Exception as e:
            self.logger.error(f"每小时备份任务执行失败: {e}")
    
    def _get_current_price(self) -> float:
        """获取当前价格，带有价格验证和异常处理"""
        try:
            if hasattr(self.grid_strategy, 'exchange'):
                # 从交易所获取当前价格
                ticker = self.grid_strategy.exchange.get_ticker()
                price = ticker.get('price', 0)
                
                # 价格有效性验证
                if price and float(price) > 0:
                    current_price = float(price)
                    # 保存最后有效价格
                    if not hasattr(self, '_last_valid_price'):
                        self._last_valid_price = current_price
                    else:
                        # 价格合理性检查：新价格与上次价格差异不超过50%
                        price_change_ratio = abs(current_price - self._last_valid_price) / self._last_valid_price
                        if price_change_ratio > 0.5:
                            self.logger.warning(f"价格变化异常: {self._last_valid_price} -> {current_price}, 变化幅度: {price_change_ratio:.2%}")
                            # 如果价格变化过大，使用最后有效价格
                            return self._last_valid_price
                        else:
                            self._last_valid_price = current_price
                    
                    return current_price
                else:
                    # 价格无效，直接抛出异常（不使用fallback）
                    self.logger.error(f"获取到无效价格: {price}")
                    raise ValueError(f"无效的价格数据: {price}")
            else:
                # 如果无法获取实时价格，抛出异常而不是返回0
                self.logger.error("网格策略实例未设置exchange，无法获取价格")
                raise ValueError("无法获取价格：exchange未设置")
                
        except ValueError:
            # ValueError直接重新抛出，不使用fallback
            raise
        except Exception as e:
            self.logger.error(f"获取当前价格失败: {e}")
            # 只有在非价格验证错误时才使用fallback
            if hasattr(self, '_last_valid_price') and self._last_valid_price > 0:
                self.logger.warning(f"价格获取失败，使用最后有效价格: {self._last_valid_price}")
                return self._last_valid_price
            else:
                # 如果连最后有效价格都没有，抛出异常
                raise ValueError(f"价格获取失败且无有效fallback价格: {e}")
    
    def _get_total_capital(self) -> float:
        """获取总资金"""
        try:
            if hasattr(self.grid_strategy, 'config'):
                return float(self.grid_strategy.config.TOTAL_CAPITAL)
            else:
                self.logger.warning("无法获取总资金配置，使用默认值")
                return 10000.0  # 默认值
        except Exception as e:
            self.logger.error(f"获取总资金失败: {e}")
            return 10000.0
    
    def _get_grid_config(self) -> dict:
        """获取网格配置"""
        try:
            if hasattr(self.grid_strategy, 'config'):
                return {
                    'active_grids': getattr(self.grid_strategy.config, 'GRID_COUNT', 20),
                    'grid_spacing': getattr(self.grid_strategy.config, 'GRID_SPACING', 0.01),
                }
            else:
                return {
                    'active_grids': 20,
                    'grid_spacing': 0.01,
                }
        except Exception as e:
            self.logger.error(f"获取网格配置失败: {e}")
            return {'active_grids': 20, 'grid_spacing': 0.01}
    
    def setup_schedules(self):
        """设置定时任务"""
        # 每天0点执行每日汇总
        schedule.every().day.at("00:00").do(self.daily_summary_task)
        
        # 每周日凌晨2点执行清理任务
        schedule.every().sunday.at("02:00").do(self.weekly_cleanup_task)
        
        # 每小时执行备份任务
        schedule.every().hour.do(self.hourly_backup_task)
        
        self.logger.info("定时任务已设置完成")
        self.logger.info("- 每日汇总: 每天 00:00")
        self.logger.info("- 每周清理: 每周日 02:00")
        self.logger.info("- 每小时备份: 每小时执行")
    
    def start_scheduler(self):
        """启动定时任务调度器"""
        if self.is_running:
            self.logger.warning("调度器已在运行中")
            return
        
        self.setup_schedules()
        self.is_running = True
        
        def run_scheduler():
            self.logger.info("定时任务调度器已启动")
            while self.is_running:
                try:
                    schedule.run_pending()
                    time.sleep(60)  # 每分钟检查一次
                except Exception as e:
                    self.logger.error(f"调度器运行错误: {e}")
                    time.sleep(60)
        
        self.scheduler_thread = threading.Thread(target=run_scheduler, daemon=True)
        self.scheduler_thread.start()
        
        self.logger.info("定时任务调度器线程已启动")
    
    def stop_scheduler(self):
        """停止定时任务调度器"""
        if not self.is_running:
            self.logger.warning("调度器未在运行")
            return
        
        self.is_running = False
        schedule.clear()
        
        if self.scheduler_thread and self.scheduler_thread.is_alive():
            self.scheduler_thread.join(timeout=5)
        
        self.logger.info("定时任务调度器已停止")
    
    def run_task_now(self, task_name: str):
        """立即执行指定任务"""
        task_map = {
            'daily_summary': self.daily_summary_task,
            'weekly_cleanup': self.weekly_cleanup_task,
            'hourly_backup': self.hourly_backup_task
        }
        
        if task_name in task_map:
            self.logger.info(f"手动执行任务: {task_name}")
            task_map[task_name]()
        else:
            self.logger.error(f"未知任务: {task_name}")
    
    def get_next_run_times(self) -> dict:
        """获取下次执行时间"""
        next_runs = {}
        
        for job in schedule.jobs:
            task_name = job.job_func.__name__
            next_run = job.next_run
            if next_run:
                next_runs[task_name] = next_run.strftime('%Y-%m-%d %H:%M:%S')
        
        return next_runs
    
    def add_trade_to_summary(self, trade_type: str, grid_type: str, price: float, 
                           quantity: float, profit: float, grid_level: int, order_id: str):
        """添加交易记录到汇总模块"""
        trade_record = GridTradeRecord(
            timestamp=datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            trade_type=trade_type,
            grid_type=grid_type,
            price=price,
            quantity=quantity,
            profit=profit,
            grid_level=grid_level,
            order_id=order_id
        )
        
        grid_summary.add_trade_record(trade_record)
        self.logger.info(f"交易记录已添加到汇总: {trade_type} {quantity} @ {price}")

# 全局调度器实例
grid_scheduler = GridScheduler()

# 便捷函数
def start_grid_scheduler():
    """启动网格交易调度器"""
    grid_scheduler.start_scheduler()

def stop_grid_scheduler():
    """停止网格交易调度器"""
    grid_scheduler.stop_scheduler()

def add_trade_record(trade_type: str, grid_type: str, price: float, 
                    quantity: float, profit: float, grid_level: int, order_id: str):
    """添加交易记录"""
    grid_scheduler.add_trade_to_summary(
        trade_type, grid_type, price, quantity, profit, grid_level, order_id
    )

def run_daily_summary_now():
    """立即执行每日汇总"""
    grid_scheduler.run_task_now('daily_summary')

def get_scheduler_status() -> dict:
    """获取调度器状态"""
    return {
        'is_running': grid_scheduler.is_running,
        'next_runs': grid_scheduler.get_next_run_times()
    }