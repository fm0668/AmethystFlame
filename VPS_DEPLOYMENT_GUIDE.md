# XRP网格交易策略 VPS部署指南

## 系统要求

- **操作系统**: Ubuntu 22.04 LTS
- **CPU**: 2核心
- **内存**: 2GB RAM
- **存储**: 20GB SSD
- **网络**: 稳定的互联网连接

```
# 六六云

ssh root@104.234.155.254

wrGgvNOGpoe1

ping 104.234.155.254

```



## 快速部署

### 1. 系统准备

```bash
# 更新系统
sudo apt update && sudo apt upgrade -y

# 安装必要工具
sudo apt install -y git python3 python3-pip python3-venv screen
```

### 2. 项目部署

```bash
# 克隆项目
cd ~
git clone https://github.com/fm0668/AmethystFlame.git
cd AmethystFlame

# 创建虚拟环境
python3 -m venv venv
source venv/bin/activate

# 安装依赖
pip install --upgrade pip
pip install -r requirements.txt
```

### 3. 配置环境

```bash
# 创建配置文件
cp .env.example .env
vim .env
```

配置内容：
```bash
# Binance API配置

API_KEY=your_binance_api_key_here
API_SECRET=your_binance_secret_key_here
```

**注意：** 其他交易参数（如交易对、网格参数、风险管理等）已在代码中预设，无需在环境变量中配置。

### 4. 生产环境部署（systemd服务）

创建系统服务：
```bash
sudo vim /etc/systemd/system/xrp-grid.service
```

服务配置：
```ini
[Unit]
Description=XRP Grid Trading Strategy
After=network.target

[Service]
Type=simple
User=root
WorkingDirectory=/root/AmethystFlame
Environment=PATH=/root/AmethystFlame/venv/bin
ExecStart=/root/AmethystFlame/venv/bin/python grid_strategy_XRP.py
Restart=always
RestartSec=10

[Install]
WantedBy=multi-user.target
```

**操作步骤：**
1. 复制上述配置内容
2. 在vim编辑器中按 `i` 进入插入模式
3. 粘贴配置内容
4. 按 `Esc` 退出插入模式
5. 输入 `:wq` 保存并退出
6. 按 `Enter` 确认

启用服务：
```bash
sudo systemctl daemon-reload
sudo systemctl enable xrp-grid.service
```

## 常用命令汇总

### 启动脚本
```bash
# 启动网格交易服务
sudo systemctl start xrp-grid.service

# 查看启动状态
sudo systemctl status xrp-grid.service
```

### 停止脚本
```bash
# 停止网格交易服务
sudo systemctl stop xrp-grid.service

# 紧急停止（直接终止进程）
pkill -f "python.*grid_strategy_XRP.py"
```

### 清理脚本
```bash
# 进入项目目录
cd ~/AmethystFlame
source venv/bin/activate

# 基本清理（取消挂单）
python3 cleanup_binance_account.py

# 完全清理（包括平仓）
python3 cleanup_binance_account.py --force-close-positions
```

### 查看日志
```bash
# 查看服务日志（实时）
sudo journalctl -u xrp-grid.service -f

# 查看服务日志（最近100行）
sudo journalctl -u xrp-grid.service -n 100

# 查看应用日志
tail -f ~/AmethystFlame/logs/grid_strategy.log
```

### 重启服务
```bash
# 重启网格交易服务
sudo systemctl restart xrp-grid.service

# 重新加载配置
sudo systemctl daemon-reload
sudo systemctl restart xrp-grid.service
```

### 系统监控
```bash
# 查看系统资源
htop

# 查看磁盘使用
df -h

# 查看服务状态
sudo systemctl status xrp-grid.service
```

## 策略信息汇总

### 查看汇总报告
```bash
# 查看最新汇总
cat ~/AmethystFlame/grid_summary_reports/summary_$(date +%Y-%m-%d).txt

# 查看JSON数据
cat ~/AmethystFlame/grid_summary_reports/summary_$(date +%Y-%m-%d).json | python3 -m json.tool

# 列出所有汇总文件
ls -la ~/AmethystFlame/grid_summary_reports/
```

### 手动生成汇总
```bash
cd ~/AmethystFlame
source venv/bin/activate
python3 -c "from grid_scheduler import run_daily_summary_now; run_daily_summary_now()"
```

## 维护任务

### 日志清理
```bash
# 清理大日志文件
find ~/AmethystFlame/logs -name "*.log" -size +100M -exec truncate -s 0 {} \;

# 删除旧汇总文件（30天前）
find ~/AmethystFlame/grid_summary_reports -name "*.json" -mtime +30 -delete
find ~/AmethystFlame/grid_summary_reports -name "*.txt" -mtime +30 -delete
```

### 代码更新
```bash
# 停止服务
sudo systemctl stop xrp-grid.service

# 更新代码
cd ~/AmethystFlame
git pull origin main

# 更新依赖
source venv/bin/activate
pip install -r requirements.txt

# 重启服务
sudo systemctl start xrp-grid.service
```

## 故障排除

### 常见问题

1. **服务无法启动**
   ```bash
   # 查看详细错误
   sudo journalctl -u xrp-grid.service --no-pager
   
   # 检查配置文件
   cat ~/AmethystFlame/.env
   ```

2. **API连接失败**
   - 检查API密钥是否正确
   - 确认网络连接正常
   - 验证API权限设置

3. **内存不足**
   ```bash
   # 创建交换文件
   sudo fallocate -l 1G /swapfile
   sudo chmod 600 /swapfile
   sudo mkswap /swapfile
   sudo swapon /swapfile
   ```

### 紧急处理
```bash
# 立即停止所有交易
sudo systemctl stop xrp-grid.service
pkill -f "python.*grid_strategy_XRP.py"

# 清理所有挂单
cd ~/AmethystFlame
source venv/bin/activate
python3 cleanup_binance_account.py
```

## 安全建议

- API密钥使用只读+交易权限，禁用提现
- 设置合理的仓位和止损限制
- 定期检查交易记录和账户状态
- 保持系统和依赖包更新

---

**免责声明**: 本软件仅供学习研究使用，交易有风险，使用需谨慎。