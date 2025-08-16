#!/bin/bash

# 本脚本为 scrcpy 无线投屏自动化工具，详细功能说明请见同目录下 README.md

# ========== 配置与常量 ==========
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
readonly DEFAULT_PORT="5656"
readonly MAX_RETRIES=3
readonly RETRY_DELAY=1

# ========== 状态变量 ==========
DEVICE_IP=""           # 设备IP地址
DEVICE_ID=""          # USB设备ID
WIRELESS_ID=""        # 无线连接ID
PORT="$DEFAULT_PORT"  # 连接端口
ROTATION=""          # 屏幕方向
CONNECTION_MODE="wireless" # 连接模式：wireless/usb
CLEANUP_DONE=0

# ========== 颜色定义 ==========
readonly COLOR_INFO="\033[1;34m"  # 蓝色
readonly COLOR_SUCCESS="\033[1;32m"  # 绿色
readonly COLOR_ERROR="\033[1;31m"  # 红色
readonly COLOR_RESET="\033[0m"

# ========== 工具函数 ==========
log_step() { printf "${COLOR_INFO}==> %s${COLOR_RESET}\n" "$1"; }
log_success() { printf "${COLOR_SUCCESS}[SUCCESS] %s${COLOR_RESET}\n" "$1"; }
log_error() { printf "${COLOR_ERROR}[ERROR] %s${COLOR_RESET}\n" "$1" >&2; }
log_debug() { [ "${DEBUG:-0}" -eq 1 ] && printf "[DEBUG] %s\n" "$1" >&2; }
log_cmd() { printf "${COLOR_INFO}$ %s${COLOR_RESET}\n" "$1"; }
log_output() { printf "%s\n" "$1"; }

# 恢复设备设置
restore_device_settings() {
    local target_device="$1"
    if [ -n "$target_device" ]; then
        log_step "恢复设备设置..."
        
        # 检查设备连接状态
        if ! ./adb -s "$target_device" shell exit >/dev/null 2>&1; then
            log_error "设备已断开连接，无法恢复设置"
            return 1
        fi
        
        # 恢复 stay_awake 设置
        if [ -n "$ORIGINAL_STAY_AWAKE" ]; then
            if ./adb -s "$target_device" shell "settings put global stay_awake $ORIGINAL_STAY_AWAKE"; then
                log_debug "已恢复 stay_awake 设置"
            else
                log_error "恢复 stay_awake 设置失败"
            fi
        fi
        
        # 尝试主动锁屏（优先用SLEEP，失败则用POWER）
        if ./adb -s "$target_device" shell "input keyevent KEYCODE_SLEEP"; then
            log_debug "已通过SLEEP键锁屏"
        elif ./adb -s "$target_device" shell "input keyevent KEYCODE_POWER"; then
            log_debug "已通过POWER键锁屏"
        else
            log_error "触发锁屏失败"
        fi
        
        # 自动切换一次休眠时间，兼容部分ROM锁屏恢复
        local orig_timeout
        orig_timeout=$(./adb -s "$target_device" shell "settings get system screen_off_timeout" | tr -d '\r')
        if [ -n "$orig_timeout" ]; then
            ./adb -s "$target_device" shell "settings put system screen_off_timeout 60000"
            ./adb -s "$target_device" shell "settings put system screen_off_timeout $orig_timeout"
            log_debug "已自动切换休眠时间以兼容锁屏恢复"
        fi
        # 最后恢复锁屏设置
        if [ -n "$ORIGINAL_LOCKSCREEN" ]; then
            if ./adb -s "$target_device" shell "settings put secure lockscreen.disabled $ORIGINAL_LOCKSCREEN"; then
                log_debug "已恢复锁屏设置"
            else
                log_error "恢复锁屏设置失败"
            fi
        fi
        
        log_success "设备设置已恢复"
        return 0
    fi
    return 1
}

cleanup() {
    [ "$CLEANUP_DONE" -eq 1 ] && return
    CLEANUP_DONE=1
    
    # 根据当前模式获取设备标识符
    local target_device
    if [ "${DEVICE_INFO[mode]}" = "usb" ]; then
        target_device="${DEVICE_INFO[id]}"
    else
        target_device="${DEVICE_INFO[ip]}:${DEVICE_INFO[port]}"
    fi

    # 如果有连接的设备，恢复设置
    if [ -n "$target_device" ]; then
        restore_device_settings "$target_device"
    fi
    
    log_debug "执行清理操作"
    exit ${1:-0}
}

# 错误处理函数
die() {
    log_error "$1"
    cleanup 1
}

show_help() {
    cat << EOF
scrcpy 无线投屏脚本 (支持方向控制)
用法: $0 [-i IP] [-p PORT] [-r 0|1|3] [-u|--usb] [-h]
选项:
 -i IP     指定设备 IP (默认: 自动检测或使用上次连接的IP)
 -p PORT   指定端口 (默认: $DEFAULT_PORT)
 -r ROT    设置屏幕方向 (0=竖屏, 1=横屏右, 3=横屏左)
 -u, --usb 仅使用USB方式投屏（不启用无线）
 -d        调试模式
 -h        显示帮助信息

示例:
 $0 -i 192.168.1.100 -r 1 # 横屏投屏
 $0 -r 0 # 竖屏默认IP
 $0 -u   # 仅USB投屏
EOF
    exit 0
}

# ========== 设备管理函数 ==========
check_environment() {
    cd "$SCRIPT_DIR" || die "无法进入脚本目录"
    
    local missing_files=()
    for file in scrcpy adb; do
        [ ! -f "./$file" ] && missing_files+=("$file")
    done
    
    if [ ${#missing_files[@]} -gt 0 ]; then
        die "未找到必要的程序文件：${missing_files[*]}\n请确保程序文件位于脚本同一目录下"
    fi
    
    # 检查执行权限
    for file in scrcpy adb; do
        [ ! -x "./$file" ] && chmod +x "./$file"
    done
}


# 尝试通过 adb connect 连接设备
adb_connect() {
    local ip="$1"
    log_debug "执行: ./adb connect $ip:$PORT"
    ./adb connect "$ip:$PORT" 2>&1
}

# 检查设备是否在线
adb_check_online() {
    local ip="$1"
    log_debug "执行: ./adb -s $ip:$PORT shell exit"
    ./adb -s "$ip:$PORT" shell exit >/dev/null 2>&1
}

# 检查设备状态
check_device_status() {
    local device_id="$1"
    
    if [ -z "$device_id" ]; then
        die "设备ID为空"
    fi
    
    local status
    status=$(./adb -s "$device_id" get-state 2>&1)
    
    case "$status" in
        "device") return 0 ;;
        "unauthorized") die "设备未授权，请在设备上确认USB调试请求" ;;
        "offline") die "设备离线" ;;
        *) die "设备状态异常: $status" ;;
    esac
}

# 获取设备IP地址
get_device_ip() {
    local device_id="$1"
    local ip
    
    # 尝试多种方法获取IP
    for cmd in "ip addr show wlan0" "ifconfig wlan0"; do
        ip=$(./adb -s "$device_id" shell "$cmd" 2>/dev/null | grep -w "inet" | grep -oE '[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+' | head -n1)
        if [ -n "$ip" ]; then
            echo "$ip"
            return 0
        fi
    done
    
    return 1
}

# 检查WiFi状态
check_wifi_status() {
    local device_id="$1"
    local wifi_state
    
    wifi_state=$(./adb -s "$device_id" shell "settings get global wifi_on" 2>/dev/null)
    [ "$wifi_state" != "1" ] && die "WiFi未启用，请先开启设备的WiFi"
    
    # 检查是否已连接到WiFi网络
    if ! ./adb -s "$device_id" shell "dumpsys wifi" | grep -q "Wi-Fi is enabled"; then
        die "WiFi未连接到网络，请先连接WiFi"
    fi
}

detect_wireless_device() {
    WIRELESS_ID=$(./adb devices | awk '/device$/{print $1}' | grep -E '^[0-9]+\.[0-9]+\.[0-9]+\.[0-9]+:[0-9]+$' | head -n1)
    if [ -n "$WIRELESS_ID" ]; then
        DEVICE_IP=$(echo "$WIRELESS_ID" | cut -d: -f1)
        return 0
    fi
    return 1
}

connect_device() {
    local retries=0
    local success=0

    while [ $retries -lt $MAX_RETRIES ]; do
        log_step "尝试连接设备: ${DEVICE_INFO[ip]}:${DEVICE_INFO[port]} (第 $((retries + 1))/$MAX_RETRIES 次)"
        
        # 执行连接命令
        local connect_cmd="./adb connect ${DEVICE_INFO[ip]}:${DEVICE_INFO[port]}"
        log_cmd "$connect_cmd"
        local connect_output
        connect_output=$($connect_cmd 2>&1)
        log_output "$connect_output"

        # 检查连接状态
        local check_cmd="./adb -s ${DEVICE_INFO[ip]}:${DEVICE_INFO[port]} shell exit"
        log_cmd "$check_cmd"
        if $check_cmd >/dev/null 2>&1; then
            log_success "无线连接成功"
            success=1
            break
        else
            log_step "获取设备列表:"
            local devices_cmd="./adb devices"
            log_cmd "$devices_cmd"
            local devices_output
            devices_output=$($devices_cmd)
            log_output "$devices_output"
        fi

        retries=$((retries + 1))
        if [ $retries -lt $MAX_RETRIES ]; then
            log_step "尝试 $retries/$MAX_RETRIES: 重试连接..."
            sleep $RETRY_DELAY
        fi
    done

    if [ $success -eq 0 ]; then
        log_error "无法建立无线连接\n提示: 无线连接可能因以下原因被中断:\n 1. 设备重启\n 2. USB调试被禁用\n 3. WiFi网络改变\n 4. 开发者选项被重置\n如遇以上情况，请重新USB连接设备并运行脚本。"
        return 1
    fi

    return 0
}

# ========== 设备控制函数 ==========
set_rotation() {
    log_step "设置屏幕方向: $ROTATION"
    if ./adb shell "settings put system accelerometer_rotation 0 && settings put system user_rotation $ROTATION"; then
        log_success "方向设置成功"
        return 0
    fi
    log_error "无法设置屏幕方向"
    return 1
}

get_target_device() {
    if [ "$CONNECTION_MODE" = "usb" ]; then
        echo "$DEVICE_ID"
    else
        echo "$DEVICE_IP:$PORT"
    fi
}

start_scrcpy() {
    local target_device
    target_device=$(get_target_device)
    local scrcpy_opts=()
    
    log_debug "使用设备: $target_device"
    
    # 验证设备连接状态
    if ! ./adb -s "$target_device" shell echo ok >/dev/null 2>&1; then
        die "设备未连接或状态异常"
    fi
    
    # 保存当前设备设置
    log_step "保存设备设置..."
    # 保存当前的 stay_awake 设置
    local current_stay_awake
    current_stay_awake=$(./adb -s "$target_device" shell "settings get global stay_awake") || current_stay_awake="0"
    export ORIGINAL_STAY_AWAKE="$current_stay_awake"
    # 保存当前的锁屏设置
    local current_lockscreen
    current_lockscreen=$(./adb -s "$target_device" shell "settings get secure lockscreen.disabled") || current_lockscreen="0"
    export ORIGINAL_LOCKSCREEN="$current_lockscreen"
    
    # 在scrcpy期间禁用锁屏，保持唤醒
    ./adb -s "$target_device" shell "settings put secure lockscreen.disabled 1"
    ./adb -s "$target_device" shell "settings put global stay_awake 1"
    
    # 基本配置
    scrcpy_opts+=("--turn-screen-off" "--stay-awake")
    
    # 设置屏幕方向
    if [ -n "$ROTATION" ]; then
        if ! set_rotation; then
            log_error "屏幕方向设置失败，将使用默认方向"
        fi
    fi
    
    log_step "启动 scrcpy..."
    log_debug "使用选项: ${scrcpy_opts[*]}"
    
    ./scrcpy -s "$target_device" "${scrcpy_opts[@]}"
    local exit_code=$?
    
    # 处理退出状态
    case $exit_code in
        0|130|2)  # 正常退出|SIGINT|没有设备
            log_step "正在终止投屏..."
            return 0
            ;;
        *)
            log_error "scrcpy 异常退出 (错误码: $exit_code)"
            return $exit_code
            ;;
    esac
}

# ========== 信号处理函数 ==========
restore_and_exit() {
    log_debug "捕获到中断信号，正在退出..."
    # 注意：这里不直接调用 restore_device_settings
    # 让 cleanup 函数统一处理恢复操作
    trap - INT TERM  # 恢复默认信号处理
    exit 0
}

# ========== 主函数 ==========
# 新增：仅USB方式投屏标志
USE_USB_ONLY=0

parse_arguments() {
    local opt
    while getopts ":i:p:r:hdu-:" opt; do
        case $opt in
            i) DEVICE_IP="$OPTARG" ;;
            p) PORT="$OPTARG" ;;
            r) ROTATION="$OPTARG" ;;
            d) DEBUG=1 ;;
            u) CONNECTION_MODE="usb" ;;
            h) show_help ;;
            -)
                case "$OPTARG" in
                    usb) CONNECTION_MODE="usb" ;;
                    *) die "未知长选项 --$OPTARG" ;;
                esac
                ;;
            \?) die "无效选项 -$OPTARG" ;;
            :) die "选项 -$OPTARG 需要参数" ;;
        esac
    done

    # 验证参数
    if [ -n "$PORT" ] && ! [[ "$PORT" =~ ^[0-9]+$ ]]; then
        die "端口号必须是数字"
    fi

    if [ -n "$ROTATION" ] && ! [[ "$ROTATION" =~ ^[013]$ ]]; then
        die "方向参数必须是 0(竖屏), 1(横屏右), 或 3(横屏左)"
    fi
}

# 获取并验证USB设备
get_usb_device() {
    # 重置 adb 服务器
    ./adb kill-server >/dev/null 2>&1
    sleep 1
    ./adb start-server >/dev/null 2>&1
    sleep 1
    
    log_debug "检测USB设备..."
    
    # 直接获取第一个USB设备ID
    # 使用一个命令组合来确保只获取到实际的设备ID
    local device_id
    device_id=$(./adb devices | grep -v 'List of' | grep -v ':' | grep 'device$' | head -n 1 | cut -f1)
    
    if [ -z "$device_id" ]; then
        log_error "未检测到任何USB设备"
        log_error "提示: 请确保:"
        log_error "1. 设备已通过USB连接"
        log_error "2. 已在设备上启用USB调试模式"
        log_error "3. 已在设备上允许USB调试授权"
        exit 1
    fi
    
    # 验证设备状态
    if ! ./adb -s "$device_id" shell echo ok >/dev/null 2>&1; then
        log_error "设备状态异常，请重新连接设备"
        exit 1
    fi
    
    log_debug "检测到USB设备: $device_id"
    printf '%s' "$device_id"
}

# 设置USB设备
setup_usb_device() {
    # 获取设备ID并去除任何可能的空白字符
    DEVICE_ID=$(get_usb_device | tr -d '[:space:]')
    log_debug "设备ID: '$DEVICE_ID'"
    
    # 如果是无线模式，需要额外的设置
    if [ "$CONNECTION_MODE" = "wireless" ]; then
        # 检查WiFi状态
        local wifi_cmd="./adb -s \"$DEVICE_ID\" shell settings get global wifi_on"
        log_cmd "$wifi_cmd"
        local wifi_state
        wifi_state=$(eval "$wifi_cmd" 2>&1)
        log_output "$wifi_state"
        check_wifi_status "$DEVICE_ID"
        
        # 获取IP地址
        local ip_cmd="./adb -s \"$DEVICE_ID\" shell ip addr show wlan0"
        log_cmd "$ip_cmd"
        local ip_output
        ip_output=$(eval "$ip_cmd" 2>&1)
        log_output "$ip_output"
        
        DEVICE_IP=$(get_device_ip "$DEVICE_ID")
        [ -z "$DEVICE_IP" ] && die "无法获取设备IP地址，请检查WiFi连接"
        log_success "获取到设备IP: $DEVICE_IP"
        
        # 启用TCP/IP模式
        enable_tcpip_mode
    fi
}

# 启用TCP/IP模式
enable_tcpip_mode() {
    # 只在无线模式下启用TCP/IP
    if [ "${DEVICE_INFO[mode]}" != "wireless" ]; then
        return 0
    fi

    log_step "启用TCP/IP模式..."
    local tcpip_cmd="./adb -s ${DEVICE_INFO[id]} tcpip ${DEVICE_INFO[port]}"
    log_cmd "$tcpip_cmd"
    
    local tcpip_output
    tcpip_output=$($tcpip_cmd 2>&1)
    local tcpip_code=$?
    log_output "$tcpip_output"
    
    if ! echo "$tcpip_output" | grep -Eqi "restarting in (tcpip|TCP) mode|already running as (tcpip|TCP)"; then
        log_error "adb tcpip 失败，退出码: $tcpip_code"
        die "无法启动TCP/IP模式"
    fi
    
    log_success "TCP/IP模式启用成功"
    sleep 2 # 等待ADB重启
}

# 连接设备主函数
connect_to_device() {
    if [ "${DEVICE_INFO[mode]}" = "usb" ]; then
        log_step "仅使用USB方式投屏"
        setup_usb_device
        return
    fi

    # 检查现有无线连接
    if detect_wireless_device; then
        log_step "检测到已连接的无线设备: ${DEVICE_INFO[wireless_id]}"
        if [ -n "${DEVICE_INFO[ip]}" ] && [ "${DEVICE_INFO[ip]}" != "$(echo "${DEVICE_INFO[wireless_id]}" | cut -d: -f1)" ]; then
            connect_device || die "无法连接到指定IP的设备"
        fi
        return 0
    fi

    # 尝试使用指定IP连接
    if [ -n "${DEVICE_INFO[ip]}" ]; then
        connect_device && return 0
    fi

    # 尝试USB连接并转为无线模式
    setup_usb_device
}

main() {
    trap cleanup EXIT INT TERM
    
    check_environment
    parse_arguments "$@"
    
    # 开启调试模式以查看详细信息
    DEBUG=1
    
    log_debug "启动参数: IP=$DEVICE_IP, PORT=$PORT, ROTATION=$ROTATION, MODE=$CONNECTION_MODE"
    
    # 尝试连接设备
    connect_to_device
    
    # 启动投屏
    start_scrcpy
}

main "$@"
