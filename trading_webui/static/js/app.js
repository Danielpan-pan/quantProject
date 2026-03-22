/**
 * 交易系统前端 JavaScript
 */

// 全局变量
let socket = null;
let marketData = {};
let orderData = {};
let tradeData = {};
let positionData = {};
let accountData = {};
let alertCounts = {
    repeat_open: 0,
    repeat_close: 0,
    repeat_cancel: 0,
    total: 0
};

// 初始化
document.addEventListener('DOMContentLoaded', function() {
    initWebSocket();
    initEventHandlers();
    initTabs();
    updateClock();
    setInterval(updateClock, 1000);
    loadConfig();
    loadSavedSubscriptions();
    requestNotificationPermission();
});

// 请求通知权限
function requestNotificationPermission() {
    if ('Notification' in window && Notification.permission === 'default') {
        // 延迟请求，避免在页面加载时立即弹出
        setTimeout(() => {
            Notification.requestPermission().then(permission => {
                if (permission === 'granted') {
                    console.log('通知权限已授予');
                } else {
                    console.log('通知权限被拒绝');
                }
            });
        }, 3000); // 3秒后请求
    }
}

// 初始化 WebSocket
function initWebSocket() {
    socket = io();
    
    socket.on('connect', function() {
        console.log('WebSocket 已连接');
        addLog('INFO', 'WebSocket 连接成功');
    });
    
    socket.on('disconnect', function() {
        console.log('WebSocket 已断开');
        addLog('WARNING', 'WebSocket 连接断开');
    });
    
    socket.on('connection_status', function(data) {
        updateConnectionStatus(data);
    });
    
    socket.on('tick_update', function(data) {
        updateTick(data);
    });
    
    socket.on('order_update', function(data) {
        updateOrder(data);
    });
    
    socket.on('trade_update', function(data) {
        updateTrade(data);
    });
    
    socket.on('position_update', function(data) {
        updatePosition(data);
    });
    
    socket.on('account_update', function(data) {
        updateAccount(data);
    });
    
    socket.on('log', function(data) {
        addLog(data.level, data.msg, data.time);
    });
    
    socket.on('alert', function(data) {
        handleAlert(data);
    });
}

// 初始化事件处理器
function initEventHandlers() {
    // 连接按钮
    document.getElementById('connectBtn').addEventListener('click', connect);
    document.getElementById('disconnectBtn').addEventListener('click', disconnect);
    
    // 订阅按钮
    document.getElementById('subscribeBtn').addEventListener('click', subscribe);
    
    // 风控按钮
    document.getElementById('pauseTradingBtn').addEventListener('click', pauseTrading);
    document.getElementById('resumeTradingBtn').addEventListener('click', resumeTrading);
    document.getElementById('cancelAllBtn').addEventListener('click', cancelAll);
    document.getElementById('configBtn').addEventListener('click', openConfigModal);
    
    // 日志按钮
    document.getElementById('clearLogBtn').addEventListener('click', clearLog);
    
    // 加载初始数据
    loadInitialData();
}

// 初始化标签页
function initTabs() {
    const tabButtons = document.querySelectorAll('.tab-button');
    tabButtons.forEach(button => {
        button.addEventListener('click', function() {
            const tabName = this.getAttribute('data-tab');
            switchTab(tabName);
        });
    });
}

// 切换标签页
function switchTab(tabName) {
    // 隐藏所有面板
    const panels = document.querySelectorAll('.tab-panel');
    panels.forEach(panel => panel.classList.remove('active'));
    
    // 显示选中的面板
    const targetPanel = document.getElementById(tabName + 'Panel');
    if (targetPanel) {
        targetPanel.classList.add('active');
    }
    
    // 更新按钮状态
    const buttons = document.querySelectorAll('.tab-button');
    buttons.forEach(button => {
        button.classList.remove('active');
        if (button.getAttribute('data-tab') === tabName) {
            button.classList.add('active');
        }
    });
}

// 更新时钟
function updateClock() {
    const now = new Date();
    const timeStr = now.toTimeString().split(' ')[0];
    const dateStr = now.toLocaleDateString('zh-CN');
    
    document.getElementById('currentTime').textContent = timeStr;
    document.getElementById('currentDate').textContent = dateStr;
}

// 连接服务器
async function connect() {
    const config = {
        '交易服务器': document.getElementById('tradeServer').value,
        '行情服务器': document.getElementById('marketServer').value,
        '经纪商代码': document.getElementById('brokerId').value,
        '用户名': document.getElementById('userid').value,
        '密码': document.getElementById('password').value,
        '产品名称': document.getElementById('appid').value,
        '授权编码': document.getElementById('authcode').value
    };
    
    try {
        const response = await fetch('/api/connect', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify(config)
        });
        
        const result = await response.json();
        if (result.success) {
            addLog('INFO', result.message);
            document.getElementById('connectBtn').disabled = true;
            document.getElementById('disconnectBtn').disabled = false;
        } else {
            addLog('ERROR', result.message);
            alert('连接失败: ' + result.message);
        }
    } catch (error) {
        console.error('连接失败:', error);
        addLog('ERROR', '连接失败: ' + error.message);
        alert('连接失败: ' + error.message);
    }
}

// 断开连接
async function disconnect() {
    try {
        const response = await fetch('/api/disconnect', {
            method: 'POST'
        });
        
        const result = await response.json();
        if (result.success) {
            addLog('INFO', result.message);
            document.getElementById('connectBtn').disabled = false;
            document.getElementById('disconnectBtn').disabled = true;
        }
    } catch (error) {
        console.error('断开失败:', error);
        addLog('ERROR', '断开失败: ' + error.message);
    }
}

// 订阅行情
async function subscribe() {
    const symbol = document.getElementById('subscribeSymbol').value;
    const exchange = document.getElementById('subscribeExchange').value;
    
    if (!symbol) {
        alert('请输入合约代码');
        return;
    }
    
    try {
        console.log(`订阅合约: ${symbol}.${exchange}`);
        const response = await fetch('/api/subscribe', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({symbol, exchange})
        });
        
        const result = await response.json();
        console.log('订阅响应:', result);
        
        if (result.success) {
            addLog('INFO', result.message);
            // 清空输入框
            document.getElementById('subscribeSymbol').value = '';
            // 刷新订阅列表
            console.log('订阅成功，刷新订阅列表...');
            await loadSavedSubscriptions();
        } else {
            addLog('ERROR', result.message);
            alert('订阅失败: ' + result.message);
        }
    } catch (error) {
        console.error('订阅失败:', error);
        addLog('ERROR', '订阅失败: ' + error.message);
    }
}

// 加载已保存的订阅列表
async function loadSavedSubscriptions() {
    try {
        console.log('正在加载已保存的订阅...');
        const response = await fetch('/api/subscriptions');
        
        if (!response.ok) {
            console.error('获取订阅列表失败，HTTP状态:', response.status);
            return;
        }
        
        const result = await response.json();
        console.log('订阅列表响应:', result);
        
        if (result.success) {
            const container = document.getElementById('savedSubscriptions');
            
            if (!container) {
                console.error('找不到 savedSubscriptions 容器元素');
                return;
            }
            
            const subscriptions = result.data;
            console.log(`找到 ${subscriptions.length} 个已保存的订阅`);
            
            if (subscriptions.length === 0) {
                container.innerHTML = '<div style="color: #999; padding: 5px;">暂无订阅</div>';
                return;
            }
            
            container.innerHTML = subscriptions.map(sub => `
                <div class="subscription-item" style="display: flex; justify-content: space-between; align-items: center; padding: 5px; margin: 2px 0; border-bottom: 1px solid #eee; background: #f8f9fa;">
                    <span style="flex: 1; color: #333;">${sub.symbol}.${sub.exchange}</span>
                    <button class="btn btn-sm" style="padding: 2px 8px; font-size: 11px; background: #dc3545; color: white; border: none; border-radius: 3px; cursor: pointer;" onclick="deleteSubscription('${sub.symbol}', '${sub.exchange}')">删除</button>
                </div>
            `).join('');
            
            console.log('订阅列表已渲染');
        } else {
            console.error('获取订阅列表失败:', result.message);
        }
    } catch (error) {
        console.error('加载订阅列表失败:', error);
    }
}

// 删除订阅
async function deleteSubscription(symbol, exchange) {
    if (!confirm(`确认删除订阅 ${symbol}.${exchange}？`)) {
        return;
    }
    
    try {
        const response = await fetch('/api/subscriptions', {
            method: 'DELETE',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({symbol, exchange})
        });
        
        const result = await response.json();
        if (result.success) {
            addLog('INFO', result.message);
            // 刷新订阅列表
            loadSavedSubscriptions();
        } else {
            addLog('ERROR', result.message);
        }
    } catch (error) {
        console.error('删除订阅失败:', error);
        addLog('ERROR', '删除订阅失败: ' + error.message);
    }
}

// 发送订单
async function sendOrder(direction, offset) {
    const symbol = document.getElementById('orderSymbol').value;
    const exchange = document.getElementById('orderExchange').value;
    const price = parseFloat(document.getElementById('orderPrice').value);
    const volume = parseInt(document.getElementById('orderVolume').value);
    
    if (!symbol || !price || !volume) {
        alert('请填写完整的下单信息');
        return;
    }
    
    // 全面的下单前验证
    const vt_symbol = `${symbol}.${exchange}`;
    const validation = await comprehensiveOrderValidation({
        vt_symbol,
        symbol,
        exchange,
        direction,
        offset,
        price,
        volume
    });
    
    if (!validation.valid) {
        // 显示详细的错误信息
        showValidationErrors(validation.errors, validation.warnings);
        return;
    }
    
    // 如果有警告，询问用户是否继续
    if (validation.warnings && validation.warnings.length > 0) {
        const warningMsg = '检测到以下警告：\n\n' + 
            validation.warnings.map((w, i) => `${i + 1}. ${w}`).join('\n') +
            '\n\n是否仍要继续下单？';
        if (!confirm(warningMsg)) {
            return;
        }
    }
    
    try {
        const response = await fetch('/api/send_order', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                symbol,
                exchange,
                direction,
                offset,
                price,
                volume
            })
        });
        
        const result = await response.json();
        if (result.success) {
            addLog('INFO', `订单已发送: ${result.vt_orderid}`);
        } else {
            addLog('ERROR', '下单失败: ' + result.message);
            alert('下单失败: ' + result.message);
        }
    } catch (error) {
        console.error('下单失败:', error);
        addLog('ERROR', '下单失败: ' + error.message);
        alert('下单失败: ' + error.message);
    }
}

// 全面的下单前验证
async function comprehensiveOrderValidation(orderParams) {
    const { vt_symbol, symbol, exchange, direction, offset, price, volume } = orderParams;
    
    const errors = [];
    const warnings = [];
    let contractInfo = null;
    
    console.log('开始全面验证订单...', orderParams);
    
    // 1. 获取合约信息
    try {
        const response = await fetch(`/api/contract_info/${vt_symbol}`);
        const result = await response.json();
        if (result.success) {
            contractInfo = result.data;
        }
    } catch (error) {
        console.warn('无法获取合约信息:', error);
    }
    
    // 2. 价格验证
    const priceCheck = await validatePrice(vt_symbol, price, contractInfo);
    if (!priceCheck.valid) {
        errors.push(`价格错误: ${priceCheck.message}`);
        if (priceCheck.suggested_price) {
            errors[errors.length - 1] += `（建议: ${priceCheck.suggested_price}）`;
        }
    }
    
    // 3. 数量验证
    const volumeCheck = validateVolume(volume, contractInfo);
    if (!volumeCheck.valid) {
        errors.push(`数量错误: ${volumeCheck.message}`);
    }
    
    // 4. 资金验证（开仓时）
    if (offset === 'OPEN' || offset === '开') {
        const fundsCheck = await validateFunds(symbol, exchange, direction, price, volume, contractInfo);
        if (!fundsCheck.valid) {
            errors.push(`资金不足: ${fundsCheck.message}`);
        } else if (fundsCheck.warning) {
            warnings.push(fundsCheck.warning);
        }
    }
    
    // 5. 持仓验证（平仓时）
    if (offset === 'CLOSE' || offset === '平' || offset === 'CLOSETODAY' || offset === '平今' || offset === 'CLOSEYESTERDAY' || offset === '平昨') {
        const positionCheck = await validatePosition(vt_symbol, direction, volume);
        if (!positionCheck.valid) {
            errors.push(`持仓不足: ${positionCheck.message}`);
        }
    }
    
    // 6. 市场状态验证
    const marketCheck = validateMarketHours();
    if (!marketCheck.valid) {
        warnings.push(marketCheck.message);
    }
    
    console.log('验证结果:', { valid: errors.length === 0, errors, warnings });
    
    return {
        valid: errors.length === 0,
        errors,
        warnings
    };
}

// 验证价格
async function validatePrice(vt_symbol, price, contractInfo) {
    if (!contractInfo) {
        // 无合约信息时的基本验证
        if (price <= 0) {
            return { valid: false, message: '价格必须大于0' };
        }
        return { valid: true };
    }
    
    const pricetick = contractInfo.pricetick;
    
    if (price <= 0) {
        return { valid: false, message: '价格必须大于0' };
    }
    
    // 检查价格是否为最小变动价位的整数倍
    const remainder = Math.abs(price % pricetick);
    const tolerance = 0.0000001;
    
    if (remainder > tolerance && Math.abs(remainder - pricetick) > tolerance) {
        const lower = Math.floor(price / pricetick) * pricetick;
        const upper = Math.ceil(price / pricetick) * pricetick;
        const suggested = Math.abs(price - lower) < Math.abs(price - upper) ? lower : upper;
        
        return {
            valid: false,
            message: `价格 ${price} 不符合最小变动价位 ${pricetick}`,
            suggested_price: suggested.toFixed(Math.max(0, -Math.log10(pricetick)))
        };
    }
    
    return { valid: true };
}

// 验证数量
function validateVolume(volume, contractInfo) {
    if (volume <= 0) {
        return { valid: false, message: '数量必须大于0' };
    }
    
    if (!Number.isInteger(volume)) {
        return { valid: false, message: '数量必须是整数' };
    }
    
    if (contractInfo && contractInfo.min_volume && volume < contractInfo.min_volume) {
        return { 
            valid: false, 
            message: `数量不能小于最小交易单位 ${contractInfo.min_volume}` 
        };
    }
    
    // 检查是否超过风控阈值（假设最大100手）
    if (volume > 100) {
        return { 
            valid: false, 
            message: `单笔数量不能超过 100 手（当前风控设置）` 
        };
    }
    
    return { valid: true };
}

// 验证资金充足性（开仓）
async function validateFunds(symbol, exchange, direction, price, volume, contractInfo) {
    // 获取账户信息
    const accounts = Object.values(accountData);
    if (accounts.length === 0) {
        return { 
            valid: true, 
            warning: '无法获取账户信息，无法验证资金充足性' 
        };
    }
    
    const account = accounts[0]; // 使用第一个账户
    const available = account.available || 0;
    
    // 计算所需保证金
    let requiredMargin = 0;
    
    if (contractInfo && contractInfo.size) {
        // 合约价值 = 价格 × 合约乘数 × 数量
        const contractValue = price * contractInfo.size * volume;
        // 保证金比例（假设10%，实际应该从配置或合约信息获取）
        const marginRatio = 0.10;
        requiredMargin = contractValue * marginRatio;
    } else {
        // 无合约信息时的估算（假设每手需要5000元保证金）
        requiredMargin = volume * 5000;
    }
    
    console.log('资金验证:', { available, requiredMargin, volume });
    
    if (available < requiredMargin) {
        return {
            valid: false,
            message: `需要保证金 ${requiredMargin.toFixed(2)} 元，可用资金仅 ${available.toFixed(2)} 元，差额 ${(requiredMargin - available).toFixed(2)} 元`
        };
    }
    
    // 如果资金紧张（小于所需保证金的1.2倍），发出警告
    if (available < requiredMargin * 1.2) {
        return {
            valid: true,
            warning: `资金较紧张：所需保证金 ${requiredMargin.toFixed(2)} 元，可用资金 ${available.toFixed(2)} 元`
        };
    }
    
    return { valid: true };
}

// 验证持仓充足性（平仓）
async function validatePosition(vt_symbol, direction, volume) {
    console.log('持仓验证开始:', { vt_symbol, direction, volume });
    console.log('当前持仓数据:', positionData);
    
    // 查找对应的持仓
    let targetPosition = null;
    
    for (const position of Object.values(positionData)) {
        console.log('检查持仓:', position);
        
        if (position.symbol === vt_symbol || position.vt_symbol === vt_symbol) {
            // 平仓逻辑：
            // - 卖出平仓（direction=SHORT）需要匹配多头持仓（position.direction=LONG）
            // - 买入平仓（direction=LONG）需要匹配空头持仓（position.direction=SHORT）
            const posDirection = position.direction;
            
            console.log('合约匹配，检查方向:', { 
                orderDirection: direction, 
                positionDirection: posDirection 
            });
            
            // 标准化方向比较
            const isOrderLong = direction === 'LONG' || direction === 'long' || direction === '多';
            const isOrderShort = direction === 'SHORT' || direction === 'short' || direction === '空';
            const isPosLong = posDirection === 'LONG' || posDirection === 'long' || posDirection === '多';
            const isPosShort = posDirection === 'SHORT' || posDirection === 'short' || posDirection === '空';
            
            // 买入平仓 -> 平空头持仓
            if (isOrderLong && isPosShort) {
                targetPosition = position;
                console.log('找到匹配持仓: 买入平仓 -> 空头持仓');
                break;
            }
            // 卖出平仓 -> 平多头持仓
            if (isOrderShort && isPosLong) {
                targetPosition = position;
                console.log('找到匹配持仓: 卖出平仓 -> 多头持仓');
                break;
            }
        }
    }
    
    if (!targetPosition) {
        console.log('未找到匹配的持仓');
        return {
            valid: false,
            message: `没有可平仓位（合约: ${vt_symbol}，订单方向: ${direction}）\n提示：卖出平仓需要多头持仓，买入平仓需要空头持仓`
        };
    }
    
    const availableVolume = targetPosition.volume || 0;
    console.log('持仓数量验证:', { availableVolume, requestedVolume: volume });
    
    if (availableVolume < volume) {
        return {
            valid: false,
            message: `持仓数量不足：需要 ${volume} 手，实际持有 ${availableVolume} 手`
        };
    }
    
    console.log('持仓验证通过');
    return { valid: true };
}

// 验证市场交易时间
function validateMarketHours() {
    const now = new Date();
    const hour = now.getHours();
    const minute = now.getMinutes();
    const day = now.getDay(); // 0=周日, 6=周六
    
    // 周末不交易
    if (day === 0 || day === 6) {
        return {
            valid: false,
            message: '当前是周末，市场未开放'
        };
    }
    
    // 简化的交易时间检查（实际应该更复杂）
    // 日盘：9:00-15:00
    // 夜盘：21:00-02:30
    const isDaySession = (hour >= 9 && hour < 15);
    const isNightSession = (hour >= 21 || hour < 3);
    
    if (!isDaySession && !isNightSession) {
        return {
            valid: true,
            message: '当前可能不在交易时间，请确认市场是否开放'
        };
    }
    
    return { valid: true };
}

// 显示验证错误
function showValidationErrors(errors, warnings) {
    let message = '';
    
    if (errors.length > 0) {
        message += '❌ 发现以下错误，无法提交订单：\n\n';
        errors.forEach((error, index) => {
            message += `${index + 1}. ${error}\n`;
        });
    }
    
    if (warnings.length > 0) {
        if (message) message += '\n';
        message += '⚠️ 警告信息：\n\n';
        warnings.forEach((warning, index) => {
            message += `${index + 1}. ${warning}\n`;
        });
    }
    
    alert(message);
}

// 验证订单价格是否符合最小变动价位（保留旧函数以兼容）
async function validateOrderPrice(vt_symbol, price) {
    try {
        const response = await fetch(`/api/contract_info/${vt_symbol}`);
        const result = await response.json();
        
        if (!result.success) {
            // 如果无法获取合约信息，仅进行基本验证
            if (price <= 0) {
                return {
                    valid: false,
                    message: '价格必须大于0'
                };
            }
            return { valid: true }; // 无合约信息时暂时放行
        }
        
        const contract = result.data;
        const pricetick = contract.pricetick;
        
        if (price <= 0) {
            return {
                valid: false,
                message: '价格必须大于0'
            };
        }
        
        // 检查价格是否为最小变动价位的整数倍
        const remainder = Math.abs(price % pricetick);
        const tolerance = 0.0000001; // 浮点数精度容差
        
        if (remainder > tolerance && Math.abs(remainder - pricetick) > tolerance) {
            // 计算建议价格（向上和向下取整）
            const lower = Math.floor(price / pricetick) * pricetick;
            const upper = Math.ceil(price / pricetick) * pricetick;
            const suggested = Math.abs(price - lower) < Math.abs(price - upper) ? lower : upper;
            
            return {
                valid: false,
                message: `价格 ${price} 不符合最小变动价位 ${pricetick}\n合约: ${contract.name || vt_symbol}`,
                suggested_price: suggested.toFixed(Math.max(0, -Math.log10(pricetick))),
                pricetick: pricetick
            };
        }
        
        return { valid: true, pricetick: pricetick };
        
    } catch (error) {
        console.error('价格验证失败:', error);
        // 验证失败时仅进行基本检查
        if (price <= 0) {
            return {
                valid: false,
                message: '价格必须大于0'
            };
        }
        return { valid: true }; // 出错时暂时放行
    }
}

// 撤单
async function cancelOrder(vt_orderid) {
    if (!confirm('确认撤销该订单？')) {
        return;
    }
    
    try {
        const response = await fetch('/api/cancel_order', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({vt_orderid})
        });
        
        const result = await response.json();
        if (result.success) {
            addLog('INFO', result.message);
        } else {
            addLog('ERROR', result.message);
            alert('撤单失败: ' + result.message);
        }
    } catch (error) {
        console.error('撤单失败:', error);
        addLog('ERROR', '撤单失败: ' + error.message);
    }
}

// 部分撤单
async function partialCancelOrder(vt_orderid) {
    const order = orderData[vt_orderid];
    if (!order) {
        alert('订单信息不存在');
        return;
    }
    
    const remainingVolume = order.volume - order.traded;
    
    if (remainingVolume <= 0) {
        alert('订单已全部成交，无需撤单');
        return;
    }
    
    const keepVolume = prompt(
        `订单委托 ${order.volume} 手，已成交 ${order.traded} 手，剩余 ${remainingVolume} 手\n\n` +
        `请输入要保留的委托数量（剩余部分将被撤销）：`,
        String(Math.floor(remainingVolume / 2))
    );
    
    if (keepVolume === null) {
        return; // 用户取消
    }
    
    const keep = parseFloat(keepVolume);
    
    if (isNaN(keep) || keep <= 0) {
        alert('保留数量必须大于0');
        return;
    }
    
    if (keep >= remainingVolume) {
        alert(`保留数量(${keep})必须小于剩余数量(${remainingVolume})`);
        return;
    }
    
    const cancelVolume = remainingVolume - keep;
    
    if (!confirm(
        `确认部分撤单？\n\n` +
        `撤销数量: ${cancelVolume} 手\n` +
        `保留数量: ${keep} 手\n\n` +
        `操作说明：\n` +
        `1. 原订单将被完全撤销\n` +
        `2. 系统将自动下一个新的 ${keep} 手的订单\n` +
        `3. 新订单的价格、方向等参数与原订单相同`
    )) {
        return;
    }
    
    try {
        const response = await fetch('/api/partial_cancel', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({
                vt_orderid: vt_orderid,
                keep_volume: keep
            })
        });
        
        const result = await response.json();
        if (result.success) {
            addLog('INFO', result.message);
            alert(result.message);
        } else {
            addLog('ERROR', result.message);
            alert('部分撤单失败: ' + result.message);
        }
    } catch (error) {
        console.error('部分撤单失败:', error);
        addLog('ERROR', '部分撤单失败: ' + error.message);
        alert('部分撤单失败: ' + error.message);
    }
}

// 全部撤单
async function cancelAll() {
    if (!confirm('确认撤销所有未成交订单？\n\n注意：此操作只撤销未成交的委托订单，不会平仓已有持仓。\n如需平仓，请在"持仓"标签页点击"平仓"按钮。')) {
        return;
    }
    
    try {
        const response = await fetch('/api/cancel_all', {
            method: 'POST'
        });
        
        const result = await response.json();
        if (result.success) {
            addLog('INFO', result.message);
            alert(result.message + '\n\n如需平仓，请在"持仓"标签页操作。');
        } else {
            addLog('ERROR', result.message);
            alert('撤单失败: ' + result.message);
        }
    } catch (error) {
        console.error('批量撤单失败:', error);
        addLog('ERROR', '批量撤单失败: ' + error.message);
        alert('批量撤单失败: ' + error.message);
    }
}

// 暂停交易
async function pauseTrading() {
    const reason = prompt('请输入暂停原因:', '手动暂停');
    if (!reason) return;
    
    try {
        const response = await fetch('/api/pause_trading', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({reason})
        });
        
        const result = await response.json();
        if (result.success) {
            addLog('WARNING', '交易已暂停');
            document.getElementById('pauseTradingBtn').disabled = true;
            document.getElementById('resumeTradingBtn').disabled = false;
            document.getElementById('tradingIndicator').textContent = '■';
            document.getElementById('tradingText').textContent = '交易已暂停';
            document.getElementById('tradingStatus').classList.add('paused');
        }
    } catch (error) {
        console.error('暂停失败:', error);
        addLog('ERROR', '暂停失败: ' + error.message);
    }
}

// 恢复交易
async function resumeTrading() {
    try {
        const response = await fetch('/api/resume_trading', {
            method: 'POST'
        });
        
        const result = await response.json();
        if (result.success) {
            addLog('INFO', '交易已恢复');
            document.getElementById('pauseTradingBtn').disabled = false;
            document.getElementById('resumeTradingBtn').disabled = true;
            document.getElementById('tradingIndicator').textContent = '▶';
            document.getElementById('tradingText').textContent = '交易已启用';
            document.getElementById('tradingStatus').classList.remove('paused');
        }
    } catch (error) {
        console.error('恢复失败:', error);
        addLog('ERROR', '恢复失败: ' + error.message);
    }
}

// 更新连接状态
function updateConnectionStatus(data) {
    const statusDot = document.getElementById('statusDot');
    const statusText = document.getElementById('statusText');
    
    if (data.connected) {
        statusDot.classList.add('connected');
        statusText.textContent = `已连接 (${data.login_time || ''})`;
    } else {
        statusDot.classList.remove('connected');
        statusText.textContent = '未连接';
    }
}

// 更新 Tick
function updateTick(data) {
    marketData[data.symbol] = data;
    
    const tbody = document.getElementById('marketTableBody');
    
    // 清除"暂无数据"提示行
    const emptyMessage = tbody.querySelector('.empty-message');
    if (emptyMessage) {
        emptyMessage.closest('tr').remove();
    }
    
    let row = tbody.querySelector(`tr[data-symbol="${data.symbol}"]`);
    
    if (!row) {
        row = tbody.insertRow();
        row.setAttribute('data-symbol', data.symbol);
    }
    
    const changePercent = 0; // 计算涨跌幅需要昨收价
    
    row.innerHTML = `
        <td>${data.symbol}</td>
        <td class="price">${data.last_price.toFixed(2)}</td>
        <td class="${changePercent >= 0 ? 'up' : 'down'}">${changePercent.toFixed(2)}%</td>
        <td>${data.bid_price_1.toFixed(2)}</td>
        <td>${data.bid_volume_1}</td>
        <td>${data.ask_price_1.toFixed(2)}</td>
        <td>${data.ask_volume_1}</td>
        <td>${data.volume}</td>
        <td>${data.datetime}</td>
    `;
}

// 更新订单
function updateOrder(data) {
    orderData[data.vt_orderid] = data;
    
    const tbody = document.getElementById('orderTableBody');
    
    // 清除"暂无数据"提示行
    const emptyMessage = tbody.querySelector('.empty-message');
    if (emptyMessage) {
        emptyMessage.closest('tr').remove();
    }
    
    let row = tbody.querySelector(`tr[data-orderid="${data.vt_orderid}"]`);
    
    if (!row) {
        row = tbody.insertRow(0);
        row.setAttribute('data-orderid', data.vt_orderid);
    }
    
    const directionText = data.direction === 'LONG' ? '买' : '卖';
    const offsetText = data.offset === 'OPEN' ? '开' : '平';
    const statusText = getStatusText(data.status);
    const canCancel = ['SUBMITTING', 'NOTTRADED', 'PARTTRADED'].includes(data.status);
    
    const remainingVolume = data.volume - data.traded;
    const canPartialCancel = canCancel && remainingVolume > 1; // 剩余数量大于1才能部分撤单
    
    row.innerHTML = `
        <td>${data.vt_orderid}</td>
        <td>${data.symbol}</td>
        <td class="${data.direction === 'LONG' ? 'up' : 'down'}">${directionText}</td>
        <td>${offsetText}</td>
        <td>${data.price.toFixed(2)}</td>
        <td>${data.volume}</td>
        <td>${data.traded}</td>
        <td class="status-${data.status.toLowerCase()}">${statusText}</td>
        <td>${data.datetime}</td>
        <td>
            ${canCancel ? `
                <button class="btn btn-sm btn-danger" onclick="cancelOrder('${data.vt_orderid}')" style="margin-right: 5px;">全部撤单</button>
                ${canPartialCancel ? `<button class="btn btn-sm btn-warning" onclick="partialCancelOrder('${data.vt_orderid}')">部分撤单</button>` : ''}
            ` : '-'}
        </td>
    `;
    
    // 更新统计
    loadStatistics();
}

// 更新成交
function updateTrade(data) {
    tradeData[data.vt_tradeid] = data;
    
    const tbody = document.getElementById('tradeTableBody');
    
    // 清除"暂无数据"提示行
    const emptyMessage = tbody.querySelector('.empty-message');
    if (emptyMessage) {
        emptyMessage.closest('tr').remove();
    }
    
    const row = tbody.insertRow(0);
    
    const directionText = data.direction === 'LONG' ? '买' : '卖';
    const offsetText = data.offset === 'OPEN' ? '开' : '平';
    
    row.innerHTML = `
        <td>${data.vt_tradeid}</td>
        <td>${data.symbol}</td>
        <td class="${data.direction === 'LONG' ? 'up' : 'down'}">${directionText}</td>
        <td>${offsetText}</td>
        <td>${data.price.toFixed(2)}</td>
        <td>${data.volume}</td>
        <td>${data.datetime}</td>
    `;
    
    // 更新统计
    loadStatistics();
}

// 更新持仓
function updatePosition(data) {
    positionData[data.vt_positionid] = data;
    
    const tbody = document.getElementById('positionTableBody');
    
    // 清除"暂无数据"提示行
    const emptyMessage = tbody.querySelector('.empty-message');
    if (emptyMessage) {
        emptyMessage.closest('tr').remove();
    }
    
    let row = tbody.querySelector(`tr[data-positionid="${data.vt_positionid}"]`);
    
    if (!row) {
        row = tbody.insertRow();
        row.setAttribute('data-positionid', data.vt_positionid);
    }
    
    const directionText = data.direction === 'LONG' ? '多' : '空';
    const pnlClass = data.pnl >= 0 ? 'up' : 'down';
    
    row.innerHTML = `
        <td>${data.symbol}</td>
        <td class="${data.direction === 'LONG' ? 'up' : 'down'}">${directionText}</td>
        <td>${data.volume}</td>
        <td>${data.frozen}</td>
        <td>${data.price.toFixed(2)}</td>
        <td class="${pnlClass}">${data.pnl.toFixed(2)}</td>
        <td>
            <button class="btn btn-sm" onclick="closePosition('${data.vt_positionid}')">平仓</button>
        </td>
    `;
}

// 更新账户
function updateAccount(data) {
    accountData[data.vt_accountid] = data;
    
    const tbody = document.getElementById('accountTableBody');
    
    // 清除"暂无数据"提示行
    const emptyMessage = tbody.querySelector('.empty-message');
    if (emptyMessage) {
        emptyMessage.closest('tr').remove();
    }
    
    let row = tbody.querySelector(`tr[data-accountid="${data.vt_accountid}"]`);
    
    if (!row) {
        row = tbody.insertRow();
        row.setAttribute('data-accountid', data.vt_accountid);
    }
    
    const pnl = data.balance - 1000000; // 假设初始资金100万
    const pnlClass = pnl >= 0 ? 'up' : 'down';
    
    row.innerHTML = `
        <td>${data.vt_accountid}</td>
        <td>${data.balance.toFixed(2)}</td>
        <td>${data.available.toFixed(2)}</td>
        <td>${data.frozen.toFixed(2)}</td>
        <td class="${pnlClass}">${pnl.toFixed(2)}</td>
    `;
}

// 处理告警
function handleAlert(data) {
    alertCounts.total++;
    
    if (data.type === 'repeat_open') {
        alertCounts.repeat_open++;
    } else if (data.type === 'repeat_close') {
        alertCounts.repeat_close++;
    } else if (data.type === 'repeat_cancel') {
        alertCounts.repeat_cancel++;
    }
    
    // 更新统计
    document.getElementById('repeatOpenCount').textContent = alertCounts.repeat_open;
    document.getElementById('repeatCloseCount').textContent = alertCounts.repeat_close;
    document.getElementById('repeatCancelCount').textContent = alertCounts.repeat_cancel;
    document.getElementById('totalAlertCount').textContent = alertCounts.total;
    
    // 添加到告警列表
    const alertList = document.getElementById('alertList');
    const alertItem = document.createElement('div');
    alertItem.className = `alert-item alert-${data.level}`;
    alertItem.innerHTML = `
        <div class="alert-header">
            <span class="alert-type">${getAlertTypeText(data.type)}</span>
            <span class="alert-time">${data.timestamp}</span>
        </div>
        <div class="alert-message">${data.message}</div>
    `;
    
    alertList.insertBefore(alertItem, alertList.firstChild);
    
    // 播放提示音
    playAlertSound();
    
    // 显示浏览器弹窗通知
    showBrowserNotification(data);
    
    // 显示页面内弹窗（对于严重告警）
    if (data.level === 'error' || data.level === 'critical') {
        showAlertDialog(data);
    }
}

// 添加日志
function addLog(level, message, time) {
    const container = document.getElementById('logContainer');
    const entry = document.createElement('div');
    entry.className = `log-entry ${level.toLowerCase()}`;
    
    const timestamp = time || new Date().toLocaleString('zh-CN');
    
    entry.innerHTML = `
        <span class="log-time">${timestamp}</span>
        <span class="log-level">${level}</span>
        <span class="log-message">${message}</span>
    `;
    
    container.appendChild(entry);
    
    // 自动滚动
    if (document.getElementById('autoScrollLog').checked) {
        container.scrollTop = container.scrollHeight;
    }
    
    // 限制日志条数
    while (container.children.length > 1000) {
        container.removeChild(container.firstChild);
    }
}

// 清空日志
function clearLog() {
    const container = document.getElementById('logContainer');
    container.innerHTML = '';
    addLog('INFO', '日志已清空');
}

// 加载初始数据
async function loadInitialData() {
    try {
        // 加载订单
        const ordersRes = await fetch('/api/data/orders');
        const ordersData = await ordersRes.json();
        if (ordersData.success) {
            ordersData.data.forEach(order => updateOrder(order));
        }
        
        // 加载成交
        const tradesRes = await fetch('/api/data/trades');
        const tradesData = await tradesRes.json();
        if (tradesData.success) {
            tradesData.data.forEach(trade => updateTrade(trade));
        }
        
        // 加载持仓
        const positionsRes = await fetch('/api/data/positions');
        const positionsData = await positionsRes.json();
        if (positionsData.success) {
            positionsData.data.forEach(position => updatePosition(position));
        }
        
        // 加载账户
        const accountsRes = await fetch('/api/data/accounts');
        const accountsData = await accountsRes.json();
        if (accountsData.success) {
            accountsData.data.forEach(account => updateAccount(account));
        }
        
        // 加载日志
        const logsRes = await fetch('/api/logs?limit=100');
        const logsData = await logsRes.json();
        if (logsData.success) {
            logsData.data.forEach(log => {
                addLog(log.level, log.msg, log.time);
            });
        }
        
        // 加载统计
        loadStatistics();
        
    } catch (error) {
        console.error('加载数据失败:', error);
    }
}

// 加载统计
async function loadStatistics() {
    try {
        const response = await fetch('/api/status');
        const result = await response.json();
        
        if (result.success) {
            const stats = result.data.statistics;
            document.getElementById('totalOrders').textContent = stats.total_orders || 0;
            document.getElementById('successOrders').textContent = stats.successful_orders || 0;
            document.getElementById('failedOrders').textContent = stats.failed_orders || 0;
            document.getElementById('cancelledOrders').textContent = stats.cancelled_orders || 0;
            document.getElementById('totalTrades').textContent = stats.total_trades || 0;
        }
    } catch (error) {
        console.error('加载统计失败:', error);
    }
}

// 加载配置
async function loadConfig() {
    try {
        const response = await fetch('/api/config?type=risk');
        const result = await response.json();
        
        if (result.success) {
            const config = result.data;
            document.getElementById('cfgRepeatOpen').value = config.repeat_open_threshold || 10;
            document.getElementById('cfgRepeatClose').value = config.repeat_close_threshold || 10;
            document.getElementById('cfgRepeatCancel').value = config.repeat_cancel_threshold || 10;
            document.getElementById('cfgTimeWindow').value = config.repeat_time_window || 60;
            document.getElementById('cfgTotalOrder').value = config.total_order_threshold || 1000;
            document.getElementById('cfgTotalCancel').value = config.total_cancel_threshold || 500;
            document.getElementById('cfgMaxVolume').value = config.max_order_volume || 100;
        }
        
        // 加载校验规则
        const validationRes = await fetch('/api/config?type=validation');
        const validationData = await validationRes.json();
        
        if (validationData.success) {
            const validation = validationData.data;
            document.getElementById('cfgCheckContract').checked = validation.check_contract !== false;
            document.getElementById('cfgCheckTickSize').checked = validation.check_tick_size !== false;
            document.getElementById('cfgCheckMaxVolume').checked = validation.check_max_volume !== false;
            document.getElementById('cfgCheckBalance').checked = validation.check_balance !== false;
            document.getElementById('cfgCheckPosition').checked = validation.check_position !== false;
            document.getElementById('cfgCheckMarket').checked = validation.check_market_status !== false;
        }
    } catch (error) {
        console.error('加载配置失败:', error);
    }
}

// 打开配置弹窗
function openConfigModal() {
    document.getElementById('configModal').style.display = 'block';
}

// 关闭配置弹窗
function closeConfigModal() {
    document.getElementById('configModal').style.display = 'none';
}

// 保存配置
async function saveConfig() {
    const riskConfig = {
        repeat_open_threshold: parseInt(document.getElementById('cfgRepeatOpen').value),
        repeat_close_threshold: parseInt(document.getElementById('cfgRepeatClose').value),
        repeat_cancel_threshold: parseInt(document.getElementById('cfgRepeatCancel').value),
        repeat_time_window: parseInt(document.getElementById('cfgTimeWindow').value),
        total_order_threshold: parseInt(document.getElementById('cfgTotalOrder').value),
        total_cancel_threshold: parseInt(document.getElementById('cfgTotalCancel').value),
        max_order_volume: parseInt(document.getElementById('cfgMaxVolume').value)
    };
    
    const validationConfig = {
        check_contract: document.getElementById('cfgCheckContract').checked,
        check_tick_size: document.getElementById('cfgCheckTickSize').checked,
        check_max_volume: document.getElementById('cfgCheckMaxVolume').checked,
        check_balance: document.getElementById('cfgCheckBalance').checked,
        check_position: document.getElementById('cfgCheckPosition').checked,
        check_market_status: document.getElementById('cfgCheckMarket').checked
    };
    
    try {
        // 保存风控配置
        const riskRes = await fetch('/api/config', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({type: 'risk', value: riskConfig})
        });
        
        // 保存校验配置
        const validationRes = await fetch('/api/config', {
            method: 'POST',
            headers: {'Content-Type': 'application/json'},
            body: JSON.stringify({type: 'validation', value: validationConfig})
        });
        
        const riskResult = await riskRes.json();
        const validationResult = await validationRes.json();
        
        if (riskResult.success && validationResult.success) {
            alert('配置已保存');
            closeConfigModal();
            addLog('INFO', '风控配置已更新');
        } else {
            alert('配置保存失败');
        }
    } catch (error) {
        console.error('保存配置失败:', error);
        alert('保存配置失败: ' + error.message);
    }
}

// 辅助函数
function getStatusText(status) {
    const statusMap = {
        'SUBMITTING': '提交中',
        'NOTTRADED': '未成交',
        'PARTTRADED': '部分成交',
        'ALLTRADED': '全部成交',
        'CANCELLED': '已撤销',
        'REJECTED': '已拒绝'
    };
    return statusMap[status] || status;
}

function getAlertTypeText(type) {
    const typeMap = {
        'repeat_open': '重复开仓',
        'repeat_close': '重复平仓',
        'repeat_cancel': '重复撤单',
        'total_order': '报单总量',
        'total_cancel': '撤单总量',
        'connection': '连接状态',
        'validation': '校验错误',
        'system': '系统'
    };
    return typeMap[type] || type;
}

function playAlertSound() {
    // 使用 Web Audio API 生成提示音
    try {
        const audioContext = new (window.AudioContext || window.webkitAudioContext)();
        const oscillator = audioContext.createOscillator();
        const gainNode = audioContext.createGain();
        
        oscillator.connect(gainNode);
        gainNode.connect(audioContext.destination);
        
        // 设置音调和音量
        oscillator.frequency.value = 800; // 频率 800Hz
        oscillator.type = 'sine'; // 正弦波
        gainNode.gain.value = 0.3; // 音量 30%
        
        // 播放 0.2 秒
        oscillator.start(audioContext.currentTime);
        oscillator.stop(audioContext.currentTime + 0.2);
        
        // 第二声
        setTimeout(() => {
            const oscillator2 = audioContext.createOscillator();
            const gainNode2 = audioContext.createGain();
            
            oscillator2.connect(gainNode2);
            gainNode2.connect(audioContext.destination);
            
            oscillator2.frequency.value = 1000;
            oscillator2.type = 'sine';
            gainNode2.gain.value = 0.3;
            
            oscillator2.start(audioContext.currentTime);
            oscillator2.stop(audioContext.currentTime + 0.2);
        }, 300);
        
    } catch (error) {
        console.error('播放提示音失败:', error);
    }
}

// 显示浏览器通知
function showBrowserNotification(data) {
    // 检查浏览器是否支持通知
    if (!('Notification' in window)) {
        console.log('浏览器不支持通知');
        return;
    }
    
    // 请求通知权限
    if (Notification.permission === 'granted') {
        createNotification(data);
    } else if (Notification.permission !== 'denied') {
        Notification.requestPermission().then(permission => {
            if (permission === 'granted') {
                createNotification(data);
            }
        });
    }
}

// 创建通知
function createNotification(data) {
    const title = `⚠️ 风控告警 - ${getAlertTypeText(data.type)}`;
    const options = {
        body: data.message,
        icon: '/static/images/alert-icon.png', // 可选：添加图标
        badge: '/static/images/badge-icon.png', // 可选：添加徽章
        tag: 'risk-alert', // 相同 tag 的通知会替换旧的
        requireInteraction: true, // 需要用户交互才关闭
        vibrate: [200, 100, 200], // 震动模式（移动设备）
    };
    
    try {
        const notification = new Notification(title, options);
        
        // 点击通知时切换到告警标签页
        notification.onclick = function() {
            window.focus();
            switchTab('alert');
            notification.close();
        };
        
        // 5秒后自动关闭
        setTimeout(() => notification.close(), 5000);
        
    } catch (error) {
        console.error('创建通知失败:', error);
    }
}

// 显示页面内弹窗告警
function showAlertDialog(data) {
    // 创建弹窗元素
    const dialog = document.createElement('div');
    dialog.className = 'alert-dialog';
    dialog.style.cssText = `
        position: fixed;
        top: 50%;
        left: 50%;
        transform: translate(-50%, -50%);
        background: white;
        padding: 30px;
        border-radius: 8px;
        box-shadow: 0 4px 20px rgba(0,0,0,0.3);
        z-index: 10000;
        max-width: 500px;
        min-width: 400px;
    `;
    
    const levelColor = data.level === 'critical' ? '#dc3545' : '#ff6b6b';
    
    dialog.innerHTML = `
        <div style="text-align: center;">
            <div style="font-size: 48px; color: ${levelColor}; margin-bottom: 20px;">⚠️</div>
            <h2 style="color: ${levelColor}; margin-bottom: 15px;">${getAlertTypeText(data.type)}</h2>
            <p style="font-size: 16px; line-height: 1.6; margin-bottom: 20px; color: #333;">${data.message}</p>
            <p style="font-size: 14px; color: #666; margin-bottom: 20px;">时间: ${data.timestamp}</p>
            <button id="closeAlertDialog" style="
                background: ${levelColor};
                color: white;
                border: none;
                padding: 10px 30px;
                border-radius: 4px;
                font-size: 16px;
                cursor: pointer;
                transition: opacity 0.2s;
            " onmouseover="this.style.opacity='0.8'" onmouseout="this.style.opacity='1'">
                我知道了
            </button>
        </div>
    `;
    
    // 创建遮罩层
    const overlay = document.createElement('div');
    overlay.className = 'alert-overlay';
    overlay.style.cssText = `
        position: fixed;
        top: 0;
        left: 0;
        right: 0;
        bottom: 0;
        background: rgba(0,0,0,0.5);
        z-index: 9999;
    `;
    
    // 添加到页面
    document.body.appendChild(overlay);
    document.body.appendChild(dialog);
    
    // 关闭按钮事件
    document.getElementById('closeAlertDialog').addEventListener('click', () => {
        document.body.removeChild(dialog);
        document.body.removeChild(overlay);
    });
    
    // 点击遮罩层关闭
    overlay.addEventListener('click', () => {
        document.body.removeChild(dialog);
        document.body.removeChild(overlay);
    });
}

function closePosition(vt_positionid) {
    const position = positionData[vt_positionid];
    if (!position) return;
    
    // 填充下单表单
    const symbolParts = position.symbol.split('.');
    document.getElementById('orderSymbol').value = symbolParts[0];
    if (symbolParts[1]) {
        document.getElementById('orderExchange').value = symbolParts[1];
    }
    
    // 获取最新价格
    const tick = marketData[position.symbol];
    if (tick) {
        document.getElementById('orderPrice').value = tick.last_price;
    }
    
    document.getElementById('orderVolume').value = position.volume;
    
    // 切换到下单面板
    alert('请在右侧下单面板确认平仓信息');
}

// 点击弹窗外部关闭
window.onclick = function(event) {
    const modal = document.getElementById('configModal');
    if (event.target == modal) {
        closeConfigModal();
    }
}

