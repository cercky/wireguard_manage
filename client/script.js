// 加载用户数据 - 修复数据结构处理
async function loadUsersData() {
    console.log('开始加载用户数据');
    const usersData = await fetchAPI('/api/users/management');
    
    if (usersData) {
        console.log('成功获取users数据:', usersData);
        
        // 根据API文档，数据可能在users字段中，也可能直接是数组
        const users = usersData.users || (Array.isArray(usersData) ? usersData : []);
        
        const usersTableBody = document.querySelector('#users-table tbody');
        usersTableBody// 用户操作函数 - 修复API调用方式
async function enableUser(userId) {
    console.log(`启用用户: ${userId}`);
    const result = await fetchAPI(`/api/users/${userId}/enable`);
    if (result && result.status === 'success') {
        showSuccessMessage(result.message || '用户已启用');
        loadUsersData();
    }
}}}

async function disableUser(userId) {
    console.log(`禁用用户: ${userId}`);
    const result = await fetchAPI(`/api/users/${userId}/disable`);
    if (result && result.status === 'success') {
        showSuccessMessage(result.message || '用户已禁用');
        loadUsersData();
    }
}

async function resetUserTraffic(userId) {
    console.log(`重置用户流量: ${userId}`);
    const result = await fetchAPI(`/api/users/${userId}/reset`);
    if (result && result.status === 'success') {
        showSuccessMessage(result.message || '用户流量已重置');
        loadUsersData();
    }
}

async function kickUser(userId) {
    console.log(`踢出用户: ${userId}`);
    const result = await fetchAPI(`/api/users/${userId}/kick`);
    if (result) {
        showSuccessMessage(result.message || '操作完成');
        loadUsersData();
    }
}

// 编辑用户功能
async function editUser(userId) {
    console.log(`编辑用户: ${userId}`);
    
    // 隐藏添加用户表单
    userForm.style.display = 'none';
    
    // 获取用户详细信息
    const usersData = await fetchAPI('/api/users/management');
    if (!usersData) return;
    
    const users = usersData.users || (Array.isArray(usersData) ? usersData : []);
    const user = users.find(u => u.id === userId);
    
    if (!user) {
        showErrorMessage('找不到指定的用户');
        return;
    }
    
    // 填充编辑表单
    currentEditUserId = userId;
    document.getElementById('edit-pubkey').value = user.peer_pubkey || '';
    document.getElementById('edit-nickname').value = user.nickname || '';
    document.getElementById('edit-mail').value = user.mail || '';
    document.getElementById('edit-phone').value = user.phone || '';
    document.getElementById('edit-bandwidth-limit').value = user.bandwidth_limit || 0;
    document.getElementById('edit-data-limit').value = user.data_limit || 0;
    document.getElementById('edit-enabled').value = user.enabled || 1;
    document.getElementById('edit-note').value = user.note || '';
    
    // 处理到期时间
    if (user.expiry_date) {
        try {
            // 将服务器时间格式转换为datetime-local格式
            const expiryDate = new Date(user.expiry_date);
            if (!isNaN(expiryDate.getTime())) {
                const localDatetime = new Date(expiryDate.getTime() - expiryDate.getTimezoneOffset() * 60000)
                    .toISOString().slice(0, 16);
                document.getElementById('edit-expiry-date').value = localDatetime;
            }
        } catch (e) {
            console.warn('无法解析到期时间:', user.expiry_date);
        }
    } else {
        document.getElementById('edit-expiry-date').value = '';
    }
    
    // 显示编辑表单
    editUserForm.style.display = 'block';
    
    // 滚动到表单位置
    editUserForm.scrollIntoView({ behavior: 'smooth' });
}

// 确认删除用户
function confirmDeleteUser(userId, userName) {
    currentDeleteUserId = userId;
    document.getElementById('delete-user-name').textContent = userName;
    deleteModal.classList.add('show');
}

// 删除用户
async function deleteUser() {
    if (!currentDeleteUserId) return;
    
    console.log(`删除用户: ${currentDeleteUserId}`);
    const result = await fetchAPI(`/api/users/${currentDeleteUserId}`, 'DELETE');
    if (result && result.status === 'success') {
        showSuccessMessage(result.message || '用户已删除');
        loadUsersData();
    }
    
    // 关闭模态框
    deleteModal.classList.remove('show');
    currentDeleteUserId = null;
}

// 格式化到期时间为API格式
function formatExpiryDate(datetimeLocal) {
    if (!datetimeLocal) return null;
    
    try {
        const date = new Date(datetimeLocal);
        return date.toISOString().slice(0, 19).replace('T', ' '); // YYYY-MM-DD HH:MM:SS
    } catch (e) {
        console.warn('无法格式化到期时间:', datetimeLocal);
        return null;
    }
}// DOMå…ƒç´ å¼•ç"¨
const dashboardTab = document.getElementById('dashboard-tab');
const usersTab = document.getElementById('users-tab');
const eventsTab = document.getElementById('events-tab');
const trafficTab = document.getElementById('traffic-tab');

const dashboardSection = document.getElementById('dashboard-section');
const usersSection = document.getElementById('users-section');
const eventsSection = document.getElementById('events-section');
const trafficSection = document.getElementById('traffic-section');

const addUserBtn = document.getElementById('add-user-btn');
const userForm = document.getElementById('user-form');
const submitUserBtn = document.getElementById('submit-user-btn');
const cancelUserBtn = document.getElementById('cancel-user-btn');

const editUserForm = document.getElementById('edit-user-form');
const updateUserBtn = document.getElementById('update-user-btn');
const cancelEditBtn = document.getElementById('cancel-edit-btn');

const deleteModal = document.getElementById('delete-confirm-modal');
const confirmDeleteBtn = document.getElementById('confirm-delete-btn');
const cancelDeleteBtn = document.getElementById('cancel-delete-btn');

// 全局变量存储当前操作的用户
let currentEditUserId = null;
let currentDeleteUserId = null;

const showHistoryBtn = document.getElementById('show-history-btn');
const daysSelect = document.getElementById('days-select');

// API基础配置
const API_BASE_URL = 'http://192.168.0.236:8000';
const REQUEST_TIMEOUT = 10000; // 10秒超时

// 标签页切换功能
function switchTab(activeTab, activeSection) {
    // 重置所有标签和内容
    [dashboardTab, usersTab, eventsTab, trafficTab].forEach(tab => tab.classList.remove('active'));
    [dashboardSection, usersSection, eventsSection, trafficSection].forEach(section => section.classList.remove('active'));
    
    // 激活选中的标签和内容
    activeTab.classList.add('active');
    activeSection.classList.add('active');
    
    // 根据选中的标签加载对应数据
    if (activeSection === dashboardSection) {
        loadDashboardData();
    } else if (activeSection === usersSection) {
        loadUsersData();
    } else if (activeSection === eventsSection) {
        loadEventsData(false);
    } else if (activeSection === trafficSection) {
        loadTrafficData();
    }
}

// 添加标签点击事件
dashboardTab.addEventListener('click', () => switchTab(dashboardTab, dashboardSection));
usersTab.addEventListener('click', () => switchTab(usersTab, usersSection));
eventsTab.addEventListener('click', () => switchTab(eventsTab, eventsSection));
trafficTab.addEventListener('click', () => switchTab(trafficTab, trafficSection));

// 页面加载完成后初始化，加载默认显示的dashboard数据
document.addEventListener('DOMContentLoaded', () => {
    loadDashboardData();
});

// 修复后的API请求函数 - 直接请求API服务器
async function fetchAPI(endpoint, method = 'GET', body = null) {
    try {
        console.log(`发起API请求: ${method} ${endpoint}`);
        
        const options = {
            method: method,
            headers: {
                'Content-Type': 'application/json',
                'Accept': 'application/json'
            },
            cache: 'no-cache'
        };
        
        // 如果有请求体，添加到options中
        if (body && (method === 'POST' || method === 'PUT')) {
            options.body = JSON.stringify(body);
        }
        
        // 设置超时
        const controller = new AbortController();
        const timeoutId = setTimeout(() => controller.abort(), REQUEST_TIMEOUT);
        options.signal = controller.signal;
        
        const fullUrl = `${API_BASE_URL}${endpoint}`;
        console.log(`发送请求到: ${fullUrl}`);
        
        const response = await fetch(fullUrl, options);
        clearTimeout(timeoutId);
        
        console.log(`API响应状态: ${response.status}`);
        
        if (!response.ok) {
            throw new Error(`HTTP ${response.status}: ${response.statusText}`);
        }
        
        const data = await response.json();
        console.log(`API请求成功: ${method} ${endpoint}`, data);
        return data;
        
    } catch (error) {
        console.error('API请求错误:', error);
        if (error.name === 'AbortError') {
            showErrorMessage('请求超时，请检查网络连接和服务器状态。');
        } else if (error.message.includes('Failed to fetch')) {
            showErrorMessage('无法连接到服务器，请检查API服务是否启动。');
        } else {
            showErrorMessage(`API请求失败: ${error.message}`);
        }
        return null;
    }
}

// 显示错误信息
function showErrorMessage(message) {
    // 移除已存在的错误消息
    const existingError = document.getElementById('api-error-message');
    if (existingError) {
        existingError.parentNode.removeChild(existingError);
    }
    
    // 创建错误消息元素
    const errorElement = document.createElement('div');
    errorElement.id = 'api-error-message';
    errorElement.className = 'api-error';
    errorElement.textContent = message;
    document.body.insertBefore(errorElement, document.body.firstChild);
    
    // 5秒后自动隐藏错误消息
    setTimeout(() => {
        if (errorElement) {
            errorElement.style.opacity = '0';
            setTimeout(() => {
                if (errorElement && errorElement.parentNode) {
                    errorElement.parentNode.removeChild(errorElement);
                }
            }, 500);
        }
    }, 5000);
}

// 显示成功信息
function showSuccessMessage(message) {
    // 移除已存在的成功消息
    const existingSuccess = document.getElementById('api-success-message');
    if (existingSuccess) {
        existingSuccess.parentNode.removeChild(existingSuccess);
    }
    
    // 创建成功消息元素
    const successElement = document.createElement('div');
    successElement.id = 'api-success-message';
    successElement.className = 'api-success';
    successElement.textContent = message;
    document.body.insertBefore(successElement, document.body.firstChild);
    
    // 3秒后自动隐藏成功消息
    setTimeout(() => {
        if (successElement) {
            successElement.style.opacity = '0';
            setTimeout(() => {
                if (successElement && successElement.parentNode) {
                    successElement.parentNode.removeChild(successElement);
                }
            }, 500);
        }
    }, 3000);
}

// 加载仪表盘数据 - 修复数据结构处理
async function loadDashboardData() {
    console.log('开始加载仪表盘数据');
    
    // 获取仪表盘统计数据
    const dashboardData = await fetchAPI('/api/dashboard');
    if (dashboardData) {
        console.log('成功获取dashboard数据:', dashboardData);
        
        // 根据API文档的响应结构处理数据
        const summary = dashboardData.summary || dashboardData;
        const traffic = dashboardData.traffic || dashboardData;
        
        // 更新概览数据
        document.getElementById('registered-users').textContent = summary.registered_users || summary.total_users || '--';
        document.getElementById('online-users').textContent = summary.online_users || '--';
        document.getElementById('active-sessions').textContent = summary.active_sessions || '--';
        document.getElementById('uptime-hours').textContent = summary.uptime_readable || (summary.uptime_hours + ' 小时') || '--';
        
        // 更新流量数据
        document.getElementById('total-upload').textContent = traffic.total_upload || formatBytes(traffic.upload_raw || 0);
        document.getElementById('total-download').textContent = traffic.total_download || formatBytes(traffic.download_raw || 0);
        document.getElementById('today-upload').textContent = traffic.today_upload || formatBytes(traffic.today_upload_raw || 0);
        document.getElementById('today-download').textContent = traffic.today_download || formatBytes(traffic.today_download_raw || 0);
    } else {
        console.error('未能获取dashboard数据');
        // 设置默认值
        ['registered-users', 'online-users', 'active-sessions', 'uptime-hours', 
         'total-upload', 'total-download', 'today-upload', 'today-download'].forEach(id => {
            document.getElementById(id).textContent = '--';
        });
    }
    
    // 获取系统状态
    const statusData = await fetchAPI('/api/status');
    if (statusData) {
        console.log('成功获取status数据:', statusData);
        
        // 根据API文档的响应结构处理数据
        const system = statusData.system || statusData;
        document.getElementById('interface').textContent = system.interface || '--';
        document.getElementById('max-handshake-age').textContent = system.max_handshake_age || '--';
    } else {
        console.error('未能获取status数据');
        document.getElementById('interface').textContent = '--';
        document.getElementById('max-handshake-age').textContent = '--';
    }
}

// 加载用户数据 - 修复数据结构处理
async function loadUsersData() {
    console.log('开始加载用户数据');
    const usersData = await fetchAPI('/api/users/management');
    
    if (usersData) {
        console.log('成功获取users数据:', usersData);
        
        // 根据API文档，数据可能在users字段中，也可能直接是数组
        const users = usersData.users || (Array.isArray(usersData) ? usersData : []);
        
        const usersTableBody = document.querySelector('#users-table tbody');
        usersTableBody.innerHTML = '';
        
        if (users.length === 0) {
            const row = document.createElement('tr');
            row.innerHTML = '<td colspan="8" style="text-align: center;">暂无用户数据</td>';
            usersTableBody.appendChild(row);
            return;
        }
        
        users.forEach(user => {
            const row = document.createElement('tr');
            
            // 格式化总流量
            const totalTraffic = (user.total_rx || 0) + (user.total_tx || 0);
            const totalTrafficReadable = user.total_rx_readable && user.total_tx_readable ? 
                `↓${user.total_rx_readable} ↑${user.total_tx_readable}` : 
                formatBytes(totalTraffic);
            
            // 状态标签
            const statusClass = user.is_online || user.status === 1 ? 'status-online' : 'status-offline';
            const statusText = user.is_online || user.status === 1 ? '在线' : '离线';
            
            // 公钥显示
            const pubkeyDisplay = user.peer_pubkey_short || truncateString(user.peer_pubkey || '', 16);
            
            row.innerHTML = `
                <td>${user.id}</td>
                <td>${user.nickname || `User_${user.id}`}</td>
                <td title="${user.peer_pubkey || ''}">${pubkeyDisplay}</td>
                <td>${user.mail || '-'}</td>
                <td><span class="status-badge ${statusClass}">${statusText}</span></td>
                <td>${totalTrafficReadable}</td>
                <td>${user.last_login || '-'}</td>
                <td>
                    <button class="primary" onclick="editUser(${user.id})" title="编辑用户">编辑</button>
                    <button class="success" onclick="resetUserTraffic(${user.id})" title="重置流量">重置</button>
                    <button class="warning" onclick="kickUser(${user.id})" title="踢出用户">踢出</button>
                    <button class="danger" onclick="confirmDeleteUser(${user.id}, '${(user.nickname || `User_${user.id}`).replace(/'/g, '\\\'')}')" title="删除用户">删除</button>
                </td>
            `;
            
            usersTableBody.appendChild(row);
        });
    } else {
        console.error('未能获取users数据');
        const usersTableBody = document.querySelector('#users-table tbody');
        usersTableBody.innerHTML = '<tr><td colspan="8" style="text-align: center;">数据加载失败</td></tr>';
    }
}

// 加载会话事件数据 - 修复数据结构处理
async function loadEventsData(showHistory = false) {
    console.log(`开始加载会话数据 (历史: ${showHistory})`);
    const endpoint = showHistory ? '/api/events/history' : '/api/events';
    const eventsData = await fetchAPI(endpoint);
    
    if (eventsData) {
        console.log('成功获取events数据:', eventsData);
        
        // 根据API文档，数据可能在events字段中，也可能直接是数组
        const events = eventsData.events || (Array.isArray(eventsData) ? eventsData : []);
        
        const eventsTableBody = document.querySelector('#events-table tbody');
        eventsTableBody.innerHTML = '';
        
        if (events.length === 0) {
            const row = document.createElement('tr');
            row.innerHTML = '<tr><td colspan="7" style="text-align: center;">暂无会话数据</td></tr>';
            eventsTableBody.appendChild(row);
            return;
        }
        
        events.forEach(event => {
            const row = document.createElement('tr');
            
            // 状态标签
            const statusClass = event.status === 'ONLINE' ? 'status-online' : 'status-offline';
            const statusText = event.status === 'ONLINE' ? '在线' : '离线';
            
            row.innerHTML = `
                <td>${event.id}</td>
                <td title="${event.peer_pubkey || ''}">${event.nickname}</td>
                <td>${event.start_time}</td>
                <td>${event.end_time || '-'}</td>
                <td><span class="status-badge ${statusClass}">${statusText}</span></td>
                <td>${event.session_tx_readable || formatBytes(event.session_tx || 0)}</td>
                <td>${event.session_rx_readable || formatBytes(event.session_rx || 0)}</td>
            `;
            
            eventsTableBody.appendChild(row);
        });
    } else {
        console.error('未能获取events数据');
        const eventsTableBody = document.querySelector('#events-table tbody');
        eventsTableBody.innerHTML = '<tr><td colspan="7" style="text-align: center;">数据加载失败</td></tr>';
    }
}

// 加载流量统计数据 - 修复数据结构处理
async function loadTrafficData() {
    console.log('开始加载流量统计数据');
    const days = daysSelect.value;
    const trafficData = await fetchAPI(`/api/traffic/chart?days=${days}`);
    
    if (trafficData) {
        console.log('成功获取traffic数据:', trafficData);
        
        // 根据API文档，数据可能在data字段中，也可能直接是数组
        const data = trafficData.data || (Array.isArray(trafficData) ? trafficData : []);
        
        // 渲染表格
        const trafficTableBody = document.querySelector('#traffic-table tbody');
        trafficTableBody.innerHTML = '';
        
        if (data.length === 0) {
            const row = document.createElement('tr');
            row.innerHTML = '<tr><td colspan="4" style="text-align: center;">暂无流量数据</td></tr>';
            trafficTableBody.appendChild(row);
            return;
        }
        
        data.forEach(day => {
            const row = document.createElement('tr');
            const totalBytes = (day.upload || 0) + (day.download || 0);
            const totalReadable = formatBytes(totalBytes);
            
            // 格式化流量数据
            const uploadReadable = day.upload_readable || formatBytes(day.upload || 0);
            const downloadReadable = day.download_readable || formatBytes(day.download || 0);
            
            row.innerHTML = `
                <td>${day.date}</td>
                <td>${uploadReadable}</td>
                <td>${downloadReadable}</td>
                <td>${totalReadable}</td>
            `;
            
            trafficTableBody.appendChild(row);
        });
        
        // 绘制图表
        drawTrafficChart(data);
    } else {
        console.error('未能获取traffic数据');
        const trafficTableBody = document.querySelector('#traffic-table tbody');
        trafficTableBody.innerHTML = '<tr><td colspan="4" style="text-align: center;">数据加载失败</td></tr>';
    }
}

// 使用原生JavaScript绘制流量图表
function drawTrafficChart(trafficData) {
    const canvas = document.getElementById('traffic-chart');
    const ctx = canvas.getContext('2d');
    
    // 设置canvas尺寸以适应容器
    canvas.width = canvas.parentElement.clientWidth;
    canvas.height = 300;
    
    // 清空画布
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    
    if (!trafficData || trafficData.length === 0) {
        // 显示无数据提示
        ctx.fillStyle = '#666';
        ctx.font = '16px Arial';
        ctx.textAlign = 'center';
        ctx.fillText('暂无流量数据', canvas.width / 2, canvas.height / 2);
        return;
    }
    
    // 计算数据范围
    const dates = trafficData.map(item => item.date);
    const uploadValues = trafficData.map(item => item.upload || 0);
    const downloadValues = trafficData.map(item => item.download || 0);
    
    const maxValue = Math.max(...uploadValues, ...downloadValues, 1); // 避免除零
    const padding = 40;
    const chartWidth = canvas.width - padding * 2;
    const chartHeight = canvas.height - padding * 2;
    
    // 绘制坐标轴
    ctx.beginPath();
    ctx.moveTo(padding, padding);
    ctx.lineTo(padding, canvas.height - padding);
    ctx.lineTo(canvas.width - padding, canvas.height - padding);
    ctx.strokeStyle = '#ccc';
    ctx.lineWidth = 1;
    ctx.stroke();
    
    // 绘制网格线和Y轴标签
    ctx.strokeStyle = '#f0f0f0';
    ctx.lineWidth = 1;
    
    for (let i = 0; i <= 5; i++) {
        const y = canvas.height - padding - (i * chartHeight / 5);
        ctx.beginPath();
        ctx.moveTo(padding, y);
        ctx.lineTo(canvas.width - padding, y);
        ctx.stroke();
        
        // 绘制数值标签
        const value = (maxValue * i / 5);
        ctx.fillStyle = '#666';
        ctx.font = '12px Arial';
        ctx.textAlign = 'right';
        ctx.fillText(formatBytes(value), padding - 10, y + 5);
    }
    
    // 绘制X轴标签和垂直网格线
    if (dates.length > 1) {
        const step = chartWidth / (dates.length - 1);
        dates.forEach((date, index) => {
            const x = padding + (index * step);
            
            // 网格线
            if (index > 0 && index < dates.length - 1) {
                ctx.strokeStyle = '#f0f0f0';
                ctx.beginPath();
                ctx.moveTo(x, padding);
                ctx.lineTo(x, canvas.height - padding);
                ctx.stroke();
            }
            
            // 日期标签
            ctx.fillStyle = '#666';
            ctx.font = '12px Arial';
            ctx.textAlign = 'center';
            const displayDate = date.length > 5 ? date.substring(5) : date; // 只显示月-日
            ctx.fillText(displayDate, x, canvas.height - padding + 20);
        });
        
        // 绘制上传流量线
        drawLine(ctx, uploadValues, '#3498db', padding, chartWidth, chartHeight, dates.length, maxValue);
        
        // 绘制下载流量线
        drawLine(ctx, downloadValues, '#e74c3c', padding, chartWidth, chartHeight, dates.length, maxValue);
    }
    
    // 添加图例
    drawLegend(ctx, canvas.width - padding - 150, padding + 20);
}

// 绘制线条
function drawLine(ctx, values, color, padding, chartWidth, chartHeight, dataPoints, maxValue) {
    if (dataPoints < 2) return;
    
    const step = chartWidth / (dataPoints - 1);
    
    ctx.beginPath();
    ctx.strokeStyle = color;
    ctx.lineWidth = 2;
    
    values.forEach((value, index) => {
        const x = padding + (index * step);
        const y = padding + chartHeight - (value / maxValue * chartHeight);
        
        if (index === 0) {
            ctx.moveTo(x, y);
        } else {
            ctx.lineTo(x, y);
        }
    });
    
    ctx.stroke();
    
    // 添加数据点
    ctx.fillStyle = color;
    values.forEach((value, index) => {
        const x = padding + (index * step);
        const y = padding + chartHeight - (value / maxValue * chartHeight);
        
        ctx.beginPath();
        ctx.arc(x, y, 3, 0, Math.PI * 2);
        ctx.fill();
    });
}

// 绘制图例
function drawLegend(ctx, x, y) {
    ctx.fillStyle = '#333';
    ctx.font = '14px Arial';
    ctx.textAlign = 'left';
    
    // 上传流量图例
    ctx.fillStyle = '#3498db';
    ctx.fillRect(x, y, 15, 3);
    ctx.fillStyle = '#333';
    ctx.fillText('上传流量', x + 20, y + 3);
    
    // 下载流量图例
    ctx.fillStyle = '#e74c3c';
    ctx.fillRect(x, y + 20, 15, 3);
    ctx.fillStyle = '#333';
    ctx.fillText('下载流量', x + 20, y + 23);
}

// 工具函数：格式化字节数
function formatBytes(bytes) {
    if (!bytes || bytes === 0) return '0B';
    
    const k = 1024;
    const sizes = ['B', 'KB', 'MB', 'GB', 'TB'];
    const i = Math.floor(Math.log(bytes) / Math.log(k));
    
    return parseFloat((bytes / Math.pow(k, i)).toFixed(1)) + sizes[i];
}

// 工具函数：截断字符串
function truncateString(str, length) {
    if (!str || str.length <= length) {
        return str || '';
    }
    return str.substring(0, length) + '...';
}

// 用户操作函数 - 修复API调用方式
async function enableUser(userId) {
    console.log(`启用用户: ${userId}`);
    const result = await fetchAPI(`/api/users/${userId}/enable`);
    if (result && result.status === 'success') {
        showSuccessMessage(result.message || '用户已启用');
        loadUsersData();
    }
}

async function disableUser(userId) {
    console.log(`禁用用户: ${userId}`);
    const result = await fetchAPI(`/api/users/${userId}/disable`);
    if (result && result.status === 'success') {
        showSuccessMessage(result.message || '用户已禁用');
        loadUsersData();
    }
}

async function resetUserTraffic(userId) {
    console.log(`重置用户流量: ${userId}`);
    const result = await fetchAPI(`/api/users/${userId}/reset`);
    if (result && result.status === 'success') {
        showSuccessMessage(result.message || '用户流量已重置');
        loadUsersData();
    }
}

// 添加用户表单控制
addUserBtn.addEventListener('click', () => {
    // 隐藏编辑表单
    editUserForm.style.display = 'none';
    // 显示/隐藏添加表单
    userForm.style.display = userForm.style.display === 'block' ? 'none' : 'block';
    
    if (userForm.style.display === 'block') {
        // 滚动到表单位置
        userForm.scrollIntoView({ behavior: 'smooth' });
    }
});

cancelUserBtn.addEventListener('click', () => {
    userForm.style.display = 'none';
    resetAddUserForm();
});

// 编辑用户表单控制
cancelEditBtn.addEventListener('click', () => {
    editUserForm.style.display = 'none';
    currentEditUserId = null;
    resetEditUserForm();
});

// 删除确认模态框控制
confirmDeleteBtn.addEventListener('click', deleteUser);

cancelDeleteBtn.addEventListener('click', () => {
    deleteModal.classList.remove('show');
    currentDeleteUserId = null;
});

// 点击模态框背景关闭
deleteModal.addEventListener('click', (e) => {
    if (e.target === deleteModal) {
        deleteModal.classList.remove('show');
        currentDeleteUserId = null;
    }
});

// 重置添加用户表单
function resetAddUserForm() {
    document.getElementById('peer-pubkey').value = '';
    document.getElementById('nickname').value = '';
    document.getElementById('mail').value = '';
    document.getElementById('phone').value = '';
    document.getElementById('bandwidth-limit').value = '';
    document.getElementById('data-limit').value = '';
    document.getElementById('expiry-date').value = '';
    document.getElementById('note').value = '';
}

// 重置编辑用户表单
function resetEditUserForm() {
    document.getElementById('edit-pubkey').value = '';
    document.getElementById('edit-nickname').value = '';
    document.getElementById('edit-mail').value = '';
    document.getElementById('edit-phone').value = '';
    document.getElementById('edit-bandwidth-limit').value = '';
    document.getElementById('edit-data-limit').value = '';
    document.getElementById('edit-expiry-date').value = '';
    document.getElementById('edit-enabled').value = '1';
    document.getElementById('edit-note').value = '';
}

// 提交用户表单 - 修复API调用
submitUserBtn.addEventListener('click', async () => {
    const peerPubkey = document.getElementById('peer-pubkey').value.trim();
    const nickname = document.getElementById('nickname').value.trim();
    const mail = document.getElementById('mail').value.trim();
    const phone = document.getElementById('phone').value.trim();
    const bandwidthLimit = parseInt(document.getElementById('bandwidth-limit').value) || 0;
    const dataLimit = parseInt(document.getElementById('data-limit').value) || 0;
    const expiryDate = document.getElementById('expiry-date').value;
    const note = document.getElementById('note').value.trim();
    
    if (!peerPubkey) {
        showErrorMessage('请输入公钥');
        return;
    }
    
    // 验证公钥格式（44字符的base64字符串）
    if (peerPubkey.length !== 44) {
        showErrorMessage('公钥格式不正确，应为44个字符');
        return;
    }
    
    // 验证邮箱格式
    if (mail && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(mail)) {
        showErrorMessage('邮箱格式不正确');
        return;
    }
    
    const userData = {
        peer_pubkey: peerPubkey,
        nickname: nickname || undefined,
        mail: mail || undefined,
        phone: phone || undefined,
        bandwidth_limit: bandwidthLimit,
        data_limit: dataLimit,
        expiry_date: formatExpiryDate(expiryDate),
        note: note || undefined
    };
    
    console.log('创建用户数据:', userData);
    const result = await fetchAPI('/api/users', 'POST', userData);
    if (result && result.status === 'success') {
        showSuccessMessage(result.message || '用户创建成功');
        // 重置并隐藏表单
        cancelUserBtn.click();
        // 重新加载用户列表
        loadUsersData();
    }
});

// 更新用户表单提交
updateUserBtn.addEventListener('click', async () => {
    if (!currentEditUserId) {
        showErrorMessage('未找到要编辑的用户');
        return;
    }
    
    const nickname = document.getElementById('edit-nickname').value.trim();
    const mail = document.getElementById('edit-mail').value.trim();
    const phone = document.getElementById('edit-phone').value.trim();
    const bandwidthLimit = parseInt(document.getElementById('edit-bandwidth-limit').value) || 0;
    const dataLimit = parseInt(document.getElementById('edit-data-limit').value) || 0;
    const enabled = parseInt(document.getElementById('edit-enabled').value);
    const expiryDate = document.getElementById('edit-expiry-date').value;
    const note = document.getElementById('edit-note').value.trim();
    
    // 验证邮箱格式
    if (mail && !/^[^\s@]+@[^\s@]+\.[^\s@]+$/.test(mail)) {
        showErrorMessage('邮箱格式不正确');
        return;
    }
    
    const userData = {
        nickname: nickname || undefined,
        mail: mail || undefined,
        phone: phone || undefined,
        bandwidth_limit: bandwidthLimit,
        data_limit: dataLimit,
        enabled: enabled,
        expiry_date: formatExpiryDate(expiryDate),
        note: note || undefined
    };
    
    console.log('更新用户数据:', userData);
    const result = await fetchAPI(`/api/users/${currentEditUserId}`, 'PUT', userData);
    if (result && result.status === 'success') {
        showSuccessMessage(result.message || '用户信息已更新');
        // 重置并隐藏表单
        cancelEditBtn.click();
        // 重新加载用户列表
        loadUsersData();
    }
});

// 显示历史事件
showHistoryBtn.addEventListener('click', () => {
    const isShowingHistory = showHistoryBtn.textContent === '查看历史';
    loadEventsData(isShowingHistory);
    showHistoryBtn.textContent = isShowingHistory ? '查看最新' : '查看历史';
});

// 更改统计天数
daysSelect.addEventListener('change', loadTrafficData);

// 窗口大小改变时重绘图表
window.addEventListener('resize', () => {
    if (trafficSection.classList.contains('active')) {
        setTimeout(loadTrafficData, 100); // 稍微延迟确保DOM更新完成
    }
});

// 初始加载仪表盘数据
loadDashboardData();

// 暴露全局函数，以便在HTML中直接调用
window.enableUser = enableUser;
window.disableUser = disableUser;
window.resetUserTraffic = resetUserTraffic;
window.kickUser = kickUser;
window.editUser = editUser;
window.confirmDeleteUser = confirmDeleteUser;

// 自动刷新功能（可选）
let autoRefreshInterval = null;

function startAutoRefresh(intervalSeconds = 30) {
    if (autoRefreshInterval) {
        clearInterval(autoRefreshInterval);
    }
    
    autoRefreshInterval = setInterval(() => {
        // 只刷新当前活跃的标签页数据
        if (dashboardSection.classList.contains('active')) {
            loadDashboardData();
        } else if (usersSection.classList.contains('active')) {
            loadUsersData();
        } else if (eventsSection.classList.contains('active')) {
            loadEventsData(showHistoryBtn.textContent === '查看最新');
        }
    }, intervalSeconds * 1000);
    
    console.log(`自动刷新已启动，间隔 ${intervalSeconds} 秒`);
}

function stopAutoRefresh() {
    if (autoRefreshInterval) {
        clearInterval(autoRefreshInterval);
        autoRefreshInterval = null;
        console.log('自动刷新已停止');
    }
}

// 启动自动刷新（30秒间隔）
startAutoRefresh(30);