#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
优雅退出管理器
当接收到停止信号时，先平掉所有持仓并撤消所有挂单，再退出程序
"""

import signal
import sys
import logging
import asyncio
import subprocess
from typing import Optional

class GracefulExitManager:
    """优雅退出管理器"""
    
    def __init__(self, strategy_instance=None, exchange_interface=None):
        """
        初始化优雅退出管理器
        
        Args:
            strategy_instance: 网格策略实例
            exchange_interface: 交易所接口实例
        """
        self.strategy = strategy_instance
        self.exchange = exchange_interface
        self.logger = logging.getLogger(__name__)
        self.exit_requested = False
        self.exit_in_progress = False
        self.exit_completed = False
        
        # 注册信号处理器
        self._register_signal_handlers()
    
    def _register_signal_handlers(self):
        """注册信号处理器"""
        try:
            # 注册SIGINT (Ctrl+C)
            signal.signal(signal.SIGINT, self._signal_handler)
            
            # 在Windows上，SIGTERM可能不可用，尝试注册
            try:
                signal.signal(signal.SIGTERM, self._signal_handler)
            except (OSError, ValueError):
                self.logger.warning("SIGTERM信号在此平台不可用")
            
            # 在Windows上注册SIGBREAK
            try:
                if hasattr(signal, 'SIGBREAK'):
                    signal.signal(signal.SIGBREAK, self._signal_handler)
            except (OSError, ValueError):
                pass
            
            self.logger.info("信号处理器注册成功")
        except Exception as e:
            self.logger.error(f"注册信号处理器失败: {e}")
    
    def _signal_handler(self, signum, frame):
        """信号处理函数"""
        signal_name = "SIGINT" if signum == signal.SIGINT else "SIGTERM"
        self.logger.info(f"接收到{signal_name}信号，开始优雅退出...")
        
        if self.exit_in_progress:
            self.logger.warning("退出已在进行中，请稍候...")
            return
        
        self.exit_requested = True
        
        # 在事件循环中执行异步退出
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # 如果事件循环正在运行，创建任务
                asyncio.create_task(self._graceful_exit())
            else:
                # 如果事件循环未运行，直接运行
                loop.run_until_complete(self._graceful_exit())
        except Exception as e:
            self.logger.error(f"执行优雅退出时出错: {e}")
            # 强制退出
            sys.exit(1)
    
    def request_exit(self):
        """请求退出（用于程序内部调用）"""
        if self.exit_in_progress:
            self.logger.warning("退出已在进行中，忽略重复请求")
            return
            
        self.logger.info("程序请求优雅退出...")
        self.exit_requested = True
        
        # 在事件循环中执行异步退出
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                # 如果事件循环正在运行，创建任务
                asyncio.create_task(self._graceful_exit())
            else:
                # 如果事件循环未运行，直接运行
                loop.run_until_complete(self._graceful_exit())
        except Exception as e:
            self.logger.error(f"执行优雅退出时出错: {e}")
            # 强制退出
            sys.exit(1)
    
    async def _graceful_exit(self):
        """执行优雅退出流程"""
        if self.exit_in_progress:
            self.logger.warning("优雅退出已在进行中，忽略重复请求")
            return
            
        self.exit_in_progress = True
        self.logger.info("=== 开始执行优雅退出流程 ===")
        
        try:
            # 1. 停止策略运行
            self.logger.info("正在停止策略...")
            await self._stop_strategy()
            self.logger.info("✓ 策略已停止")
            
            # 2. 调用清理脚本进行账户清理
            self.logger.info("正在调用清理脚本进行账户清理...")
            await self._run_cleanup_script()
            self.logger.info("✓ 账户清理完成")
            
            # 4. 保存最终状态
            self.logger.info("正在保存最终状态...")
            await self._save_final_state()
            self.logger.info("✓ 最终状态已保存")
            
            self.logger.info("=== 优雅退出流程完成 ===")
            
        except Exception as e:
            self.logger.error(f"✗ 优雅退出过程中出错: {e}")
        finally:
            # 标记退出完成，让主程序决定如何退出
            self.logger.info("优雅退出流程已完成")
            self.exit_in_progress = False
            self.exit_completed = True
    
    async def _stop_strategy(self):
        """停止策略运行"""
        if self.strategy:
            try:
                self.logger.info("停止网格策略...")
                # 设置停止标志
                if hasattr(self.strategy, 'running'):
                    self.strategy.running = False
                
                # 如果有停止方法，调用它
                if hasattr(self.strategy, 'stop'):
                    await self.strategy.stop()
                
                self.logger.info("网格策略已停止")
            except Exception as e:
                self.logger.error(f"停止策略时出错: {e}")
    
    async def _run_cleanup_script(self):
        """运行清理脚本"""
        try:
            self.logger.info("开始运行清理脚本...")
            
            # 运行清理脚本
            process = await asyncio.create_subprocess_exec(
                'python', 'cleanup_binance_account.py',
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd='.'  # 在当前目录运行
            )
            
            # 等待脚本完成
            stdout, stderr = await process.communicate()
            
            if process.returncode == 0:
                self.logger.info("清理脚本执行成功")
                # 记录输出（如果需要）
                if stdout:
                    output = stdout.decode('utf-8', errors='ignore')
                    self.logger.info(f"清理脚本输出: {output[-500:]}...")  # 只显示最后500字符
            else:
                self.logger.error(f"清理脚本执行失败，返回码: {process.returncode}")
                if stderr:
                    error = stderr.decode('utf-8', errors='ignore')
                    self.logger.error(f"清理脚本错误: {error}")
                    
        except Exception as e:
            self.logger.error(f"运行清理脚本时出错: {e}")
            # 如果清理脚本失败，回退到原有的清理方法
            self.logger.info("回退到内置清理方法...")
            await self._cancel_all_orders()
            await self._close_all_positions()
    
    async def _cancel_all_orders(self):
        """撤销所有挂单"""
        if not self.exchange:
            self.logger.warning("交易所接口未设置，跳过撤单")
            return
        
        try:
            self.logger.info("开始撤销所有挂单...")
            
            # 获取所有未成交订单
            open_orders = self.exchange.fetch_open_orders()
            
            if not open_orders:
                self.logger.info("没有需要撤销的挂单")
                return
            
            self.logger.info(f"发现 {len(open_orders)} 个挂单，开始撤销...")
            
            # 撤销所有订单
            cancelled_count = 0
            for order in open_orders:
                try:
                    self.exchange.cancel_order(order['id'], order['symbol'])
                    cancelled_count += 1
                    self.logger.info(f"已撤销订单: {order['id']}")
                except Exception as e:
                    self.logger.error(f"撤销订单 {order['id']} 失败: {e}")
            
            self.logger.info(f"撤单完成，成功撤销 {cancelled_count}/{len(open_orders)} 个订单")
            
        except Exception as e:
            self.logger.error(f"撤销挂单时出错: {e}")
    
    async def _close_all_positions(self):
        """平掉所有持仓"""
        if not self.exchange:
            self.logger.warning("交易所接口未设置，跳过平仓")
            return
        
        try:
            self.logger.info("开始平掉所有持仓...")
            
            # 获取当前持仓（返回多头和空头持仓）
            long_position, short_position = self.exchange.get_position()
            
            self.logger.info(f"当前持仓 - 多头: {long_position}, 空头: {short_position}")
            
            if long_position == 0 and short_position == 0:
                self.logger.info("没有需要平仓的持仓")
                return
            
            success_count = 0
            total_count = 0
            
            # 平掉多头持仓
            if long_position > 0:
                total_count += 1
                try:
                    self.logger.info(f"平掉多头持仓: {long_position}")
                    order = self.exchange.place_order(
                        side='sell',
                        price=None,  # 市价单
                        quantity=long_position,
                        is_reduce_only=True,
                        position_side='long',
                        order_type='market'
                    )
                    
                    if order:
                        self.logger.info(f"多头平仓订单已提交: {order.get('id', 'N/A')}")
                        success_count += 1
                    else:
                        self.logger.error("多头平仓订单提交失败")
                        
                except Exception as e:
                    self.logger.error(f"平掉多头持仓时出错: {e}")
            
            # 平掉空头持仓
            if short_position > 0:
                total_count += 1
                try:
                    self.logger.info(f"平掉空头持仓: {short_position}")
                    order = self.exchange.place_order(
                        side='buy',
                        price=None,  # 市价单
                        quantity=short_position,
                        is_reduce_only=True,
                        position_side='short',
                        order_type='market'
                    )
                    
                    if order:
                        self.logger.info(f"空头平仓订单已提交: {order.get('id', 'N/A')}")
                        success_count += 1
                    else:
                        self.logger.error("空头平仓订单提交失败")
                        
                except Exception as e:
                    self.logger.error(f"平掉空头持仓时出错: {e}")
            
            # 等待订单执行
            if success_count > 0:
                self.logger.info("等待平仓订单执行...")
                await asyncio.sleep(3)
                
                # 检查最终持仓
                final_long, final_short = self.exchange.get_position()
                self.logger.info(f"最终持仓 - 多头: {final_long}, 空头: {final_short}")
                
                if final_long == 0 and final_short == 0:
                    self.logger.info("✅ 所有持仓已成功平掉")
                else:
                    self.logger.warning(f"⚠️ 持仓未完全平掉 - 多头: {final_long}, 空头: {final_short}")
            
            self.logger.info(f"平仓完成，成功提交 {success_count}/{total_count} 个平仓订单")
            
        except Exception as e:
            self.logger.error(f"平仓时出错: {e}")
    
    async def _save_final_state(self):
        """保存最终状态"""
        try:
            self.logger.info("保存最终状态...")
            
            # 如果策略有保存状态的方法，调用它
            if self.strategy and hasattr(self.strategy, 'save_state'):
                await self.strategy.save_state()
            
            # 生成最终汇总报告
            if self.strategy and hasattr(self.strategy, 'summary_module'):
                summary_module = self.strategy.summary_module
                if summary_module and hasattr(summary_module, 'generate_summary_report'):
                    await summary_module.generate_summary_report(force=True)
                    self.logger.info("最终汇总报告已生成")
            
        except Exception as e:
            self.logger.error(f"保存最终状态时出错: {e}")
    
    def is_exit_requested(self):
        """检查是否请求退出"""
        return self.exit_requested
    
    def is_exit_completed(self):
        """检查优雅退出是否已完成"""
        return self.exit_completed
    
    def set_strategy(self, strategy):
        """设置策略实例"""
        self.strategy = strategy
    
    def set_exchange(self, exchange):
        """设置交易所接口"""
        self.exchange = exchange

# 全局退出管理器实例
exit_manager = None

def get_exit_manager():
    """获取全局退出管理器实例"""
    global exit_manager
    if exit_manager is None:
        exit_manager = GracefulExitManager()
    return exit_manager

def setup_graceful_exit(strategy=None, exchange=None):
    """设置优雅退出"""
    global exit_manager
    exit_manager = GracefulExitManager(strategy, exchange)
    return exit_manager