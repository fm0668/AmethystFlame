#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
币安账户清理脚本
用于撤销所有挂单并检查持仓状态
"""

import asyncio
import logging
from exchange_interface import ExchangeInterface
from config import Config

# 配置日志
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

class BinanceAccountCleaner:
    def __init__(self):
        """初始化币安账户清理器"""
        self.exchange = ExchangeInterface()
        
    async def get_all_open_orders(self):
        """获取所有挂单"""
        try:
            logger.info("📋 正在获取所有挂单...")
            orders = self.exchange.fetch_open_orders()
            logger.info(f"📊 找到 {len(orders)} 个挂单")
            
            if orders:
                logger.info("\n=== 当前挂单列表 ===")
                for order in orders:
                    logger.info(f"订单ID: {order['id']}, 交易对: {order['symbol']}, "
                              f"类型: {order['side']}, 数量: {order['amount']}, "
                              f"价格: {order['price']}, 状态: {order['status']}")
                logger.info("=" * 50)
            
            return orders
        except Exception as e:
            logger.error(f"❌ 获取挂单失败: {e}")
            return []
    
    async def cancel_all_orders(self):
        """撤销所有挂单"""
        try:
            orders = await self.get_all_open_orders()
            if not orders:
                logger.info("✅ 没有需要撤销的挂单")
                return True
            
            logger.info(f"🔄 开始撤销 {len(orders)} 个挂单...")
            success_count = 0
            failed_count = 0
            
            for order in orders:
                try:
                    self.exchange.cancel_order(
                        order_id=order['id'],
                        symbol=order['symbol']
                    )
                    logger.info(f"✅ 成功撤销订单: {order['id']} ({order['symbol']})")
                    success_count += 1
                    await asyncio.sleep(0.1)  # 避免请求过于频繁
                except Exception as e:
                    logger.error(f"❌ 撤销订单失败 {order['id']}: {e}")
                    failed_count += 1
            
            logger.info(f"\n📊 撤销结果: 成功 {success_count} 个, 失败 {failed_count} 个")
            return failed_count == 0
            
        except Exception as e:
            logger.error(f"❌ 撤销挂单过程出错: {e}")
            return False
    
    async def get_account_positions(self):
        """获取账户持仓信息"""
        try:
            logger.info("📋 正在获取账户持仓信息...")
            # 获取持仓信息
            long_pos, short_pos = self.exchange.get_position()
            logger.info(f"📊 当前持仓: 多头 {long_pos}, 空头 {short_pos}")
            
            positions = []
            if long_pos != 0:
                positions.append({
                    'side': 'long',
                    'size': long_pos,
                    'symbol': 'XRP/USDT'
                })
            if short_pos != 0:
                positions.append({
                    'side': 'short', 
                    'size': short_pos,
                    'symbol': 'XRP/USDT'
                })
            
            logger.info(f"📊 找到 {len(positions)} 个持仓")
            
            if positions:
                logger.info("\n=== 当前持仓状态 ===")
                for pos in positions:
                    logger.info(f"交易对: {pos['symbol']}, 方向: {pos['side']}, "
                              f"数量: {pos['size']}")
                logger.info("=" * 50)
            
            return positions
            
        except Exception as e:
            logger.error(f"❌ 获取持仓信息失败: {e}")
            return []
    
    async def close_all_positions(self, positions):
        """平掉所有持仓"""
        try:
            logger.info("🔄 开始平仓操作...")
            success_count = 0
            failed_count = 0
            
            for pos in positions:
                try:
                    side = 'sell' if pos['side'] == 'long' else 'buy'
                    quantity = pos['size']
                    
                    logger.info(f"📤 平仓 {pos['symbol']} {pos['side']} {quantity}")
                    
                    # 使用市价单平仓
                    order = self.exchange.place_order(
                        side=side,
                        price=None,  # 市价单
                        quantity=quantity,
                        is_reduce_only=True,
                        position_side=pos['side'],
                        order_type='market'
                    )
                    
                    if order:
                        logger.info(f"✅ 成功平仓: {pos['symbol']} {pos['side']} {quantity}")
                        success_count += 1
                    else:
                        logger.error(f"❌ 平仓失败: {pos['symbol']} {pos['side']} {quantity}")
                        failed_count += 1
                    
                    await asyncio.sleep(0.5)  # 避免请求过于频繁
                    
                except Exception as e:
                    logger.error(f"❌ 平仓操作失败 {pos['symbol']} {pos['side']}: {e}")
                    failed_count += 1
            
            logger.info(f"\n📊 平仓结果: 成功 {success_count} 个, 失败 {failed_count} 个")
            return failed_count == 0
            
        except Exception as e:
            logger.error(f"❌ 平仓过程出错: {e}")
            return False
    
    async def check_futures_positions(self):
        """检查合约持仓（如果有的话）"""
        try:
            logger.info("📋 正在检查合约持仓...")
            # 注意：这需要合约API权限
            # 这里只是示例，实际使用时需要根据你的交易所接口调整
            logger.info("ℹ️  合约持仓检查需要额外的API权限，请手动检查")
            return []
        except Exception as e:
            logger.info(f"ℹ️  无法检查合约持仓（可能没有合约权限）: {e}")
            return []
    
    async def cleanup_account(self):
        """完整的账户清理流程"""
        logger.info("🚀 === 开始币安账户清理 ===")
        
        # 1. 撤销所有挂单
        logger.info("\n🔄 步骤1: 撤销所有挂单")
        cancel_success = await self.cancel_all_orders()
        
        # 2. 检查持仓状态
        logger.info("\n📊 步骤2: 检查现货持仓")
        positions = await self.get_account_positions()
        
        # 3. 检查合约持仓
        logger.info("\n📊 步骤3: 检查合约持仓")
        futures_positions = await self.check_futures_positions()
        
        # 4. 再次确认没有挂单
        logger.info("\n🔍 步骤4: 最终确认挂单状态")
        final_orders = await self.get_all_open_orders()
        
        # 总结
        logger.info("\n" + "=" * 60)
        logger.info("📋 === 清理结果汇总 ===")
        logger.info(f"✅ 挂单撤销: {'成功' if cancel_success else '部分失败'}")
        logger.info(f"📊 剩余挂单: {len(final_orders)} 个")
        logger.info(f"💰 合约持仓: {len(positions)} 个持仓")
        
        if positions:
            logger.info("\n⚠️  注意: 以下持仓仍存在，需要平仓:")
            for pos in positions:
                logger.info(f"   - {pos['symbol']} {pos['side']}: {pos['size']}")
            
            # 自动平仓所有持仓
            logger.info("\n💡 自动平掉所有持仓...")
            await self.close_all_positions(positions)
        
        if final_orders:
            logger.info("\n⚠️  注意: 仍有未撤销的挂单，请手动处理")
        
        logger.info("=" * 60)
        return cancel_success and len(final_orders) == 0

async def main():
    """主函数"""
    cleaner = BinanceAccountCleaner()
    
    try:
        # 初始化交易所连接
        cleaner.exchange.initialize_exchange()
        logger.info("✅ 交易所连接初始化成功")
        
        # 执行清理
        success = await cleaner.cleanup_account()
        
        if success:
            logger.info("\n🎉 账户清理完成！")
        else:
            logger.info("\n⚠️  账户清理部分完成，请检查上述警告信息")
            
    except Exception as e:
        logger.error(f"❌ 清理过程出错: {e}")
    finally:
        # 关闭连接
        if hasattr(cleaner.exchange, 'close'):
            await cleaner.exchange.close()
        logger.info("🔚 清理脚本执行完毕")

if __name__ == "__main__":
    print("🚀 币安账户清理脚本")
    print("⚠️  警告: 此脚本将自动撤销所有挂单并平掉所有持仓")
    asyncio.run(main())