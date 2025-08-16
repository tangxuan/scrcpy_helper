#!/usr/bin/env python3
# -*- coding: utf-8 -*-

import argparse
import os
import re
import signal
import subprocess
import sys
import time
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional, Tuple

# ========== 配置与常量 ==========
DEFAULT_PORT = 5656
MAX_RETRIES = 3
RETRY_DELAY = 1

# ========== 颜色定义 ==========
class Colors:
    INFO = "\033[1;34m"     # 蓝色
    SUCCESS = "\033[1;32m"  # 绿色
    ERROR = "\033[1;31m"    # 红色
    RESET = "\033[0m"

@dataclass
class DeviceInfo:
    device_id: str = ""     # USB设备ID
    device_ip: str = ""     # 设备IP地址
    port: int = DEFAULT_PORT  # 连接端口
    rotation: Optional[int] = None  # 屏幕方向
    mode: str = "wireless"  # 连接模式：wireless/usb
    original_stay_awake: Optional[str] = None  # 原始保持唤醒设置
    original_lockscreen: Optional[str] = None  # 原始锁屏设置

class ScrcpyHelper:
    def __init__(self):
        self.script_dir = Path(__file__).parent.absolute()
        self.debug = False
        self.device_info = DeviceInfo()
        self.cleanup_done = False
        
    def log_step(self, message: str) -> None:
        print(f"{Colors.INFO}==> {message}{Colors.RESET}")

    def log_success(self, message: str) -> None:
        print(f"{Colors.SUCCESS}[SUCCESS] {message}{Colors.RESET}")

    def log_error(self, message: str) -> None:
        print(f"{Colors.ERROR}[ERROR] {message}{Colors.RESET}", file=sys.stderr)

    def log_debug(self, message: str) -> None:
        if self.debug:
            print(f"[DEBUG] {message}", file=sys.stderr)

    def log_cmd(self, command: str) -> None:
        print(f"{Colors.INFO}$ {command}{Colors.RESET}")

    def run_adb(self, args: List[str], check: bool = True, capture_output: bool = True) -> subprocess.CompletedProcess:
        cmd = ["./adb"] + args
        self.log_debug(f"执行命令: {' '.join(cmd)}")
        try:
            result = subprocess.run(cmd, check=check, capture_output=capture_output, text=True)
            return result
        except subprocess.CalledProcessError as e:
            if check:
                self.log_error(f"ADB命令执行失败: {e}")
                raise
            return e

    def restore_device_settings(self, target_device: str) -> None:
        """恢复设备设置"""
        self.log_step("恢复设备设置...")
        
        # 检查设备连接状态
        try:
            self.run_adb(["-s", target_device, "shell", "exit"])
        except subprocess.CalledProcessError:
            self.log_error("设备已断开连接，无法恢复设置")
            return

        # 恢复 stay_awake 设置
        if self.device_info.original_stay_awake is not None:
            try:
                self.run_adb(["-s", target_device, "shell", 
                            f"settings put global stay_awake {self.device_info.original_stay_awake}"])
                self.log_debug("已恢复 stay_awake 设置")
            except subprocess.CalledProcessError:
                self.log_error("恢复 stay_awake 设置失败")

        # 尝试主动锁屏
        try:
            try:
                self.run_adb(["-s", target_device, "shell", "input keyevent KEYCODE_SLEEP"])
                self.log_debug("已通过SLEEP键锁屏")
            except subprocess.CalledProcessError:
                self.run_adb(["-s", target_device, "shell", "input keyevent KEYCODE_POWER"])
                self.log_debug("已通过POWER键锁屏")
        except subprocess.CalledProcessError:
            self.log_error("触发锁屏失败")

        # 恢复锁屏设置
        if self.device_info.original_lockscreen is not None:
            try:
                self.run_adb(["-s", target_device, "shell", 
                            f"settings put secure lockscreen.disabled {self.device_info.original_lockscreen}"])
                self.log_debug("已恢复锁屏设置")
            except subprocess.CalledProcessError:
                self.log_error("恢复锁屏设置失败")

        self.log_success("设备设置已恢复")

    def cleanup(self, exit_code: int = 0) -> None:
        """清理函数"""
        if self.cleanup_done:
            return
        self.cleanup_done = True
        
        # 获取目标设备标识符
        target_device = None
        if self.device_info.mode == "usb":
            target_device = self.device_info.device_id
        elif self.device_info.device_ip:
            target_device = f"{self.device_info.device_ip}:{self.device_info.port}"

        if target_device:
            self.restore_device_settings(target_device)
        
        self.log_debug("执行清理操作")
        sys.exit(exit_code)

    def die(self, message: str) -> None:
        """错误处理函数"""
        self.log_error(message)
        self.cleanup(1)

    def check_environment(self) -> None:
        """检查运行环境"""
        os.chdir(self.script_dir)
        
        missing_files = []
        for file in ["scrcpy", "adb"]:
            if not Path(file).is_file():
                missing_files.append(file)
        
        if missing_files:
            self.die(f"未找到必要的程序文件：{', '.join(missing_files)}\n请确保程序文件位于脚本同一目录下")
        
        # 检查执行权限
        for file in ["scrcpy", "adb"]:
            path = Path(file)
            if not os.access(path, os.X_OK):
                path.chmod(path.stat().st_mode | 0o111)

    def get_usb_device(self) -> str:
        """获取USB设备ID"""
        # 重置 adb 服务器
        self.run_adb(["kill-server"], check=False)
        time.sleep(1)
        self.run_adb(["start-server"], check=False)
        time.sleep(1)
        
        self.log_debug("检测USB设备...")
        
        # 获取设备列表
        result = self.run_adb(["devices"], capture_output=True)
        
        # 查找USB设备ID
        device_id = None
        for line in result.stdout.splitlines()[1:]:  # 跳过第一行的 "List of devices attached"
            if line and ":" not in line and "device" in line:
                device_id = line.split()[0]
                break
        
        if not device_id:
            self.log_error("未检测到任何USB设备")
            self.log_error("提示: 请确保:")
            self.log_error("1. 设备已通过USB连接")
            self.log_error("2. 已在设备上启用USB调试模式")
            self.log_error("3. 已在设备上允许USB调试授权")
            sys.exit(1)
        
        # 验证设备状态
        try:
            self.run_adb(["-s", device_id, "shell", "echo", "ok"])
        except subprocess.CalledProcessError:
            self.log_error("设备状态异常，请重新连接设备")
            sys.exit(1)
        
        self.log_debug(f"检测到USB设备: {device_id}")
        return device_id

    def get_device_ip(self, device_id: str) -> Optional[str]:
        """获取设备IP地址"""
        commands = ["ip addr show wlan0", "ifconfig wlan0"]
        for cmd in commands:
            try:
                result = self.run_adb(["-s", device_id, "shell", cmd])
                match = re.search(r'inet (\d+\.\d+\.\d+\.\d+)', result.stdout)
                if match:
                    return match.group(1)
            except subprocess.CalledProcessError:
                continue
        return None

    def check_wifi_status(self, device_id: str) -> None:
        """检查WiFi状态"""
        try:
            result = self.run_adb(["-s", device_id, "shell", "settings get global wifi_on"])
            if result.stdout.strip() != "1":
                self.die("WiFi未启用，请先开启设备的WiFi")
            
            result = self.run_adb(["-s", device_id, "shell", "dumpsys wifi"])
            if "Wi-Fi is enabled" not in result.stdout:
                self.die("WiFi未连接到网络，请先连接WiFi")
        except subprocess.CalledProcessError:
            self.die("无法检查WiFi状态")

    def setup_usb_device(self) -> None:
        """设置USB设备"""
        self.device_info.device_id = self.get_usb_device()
        self.log_debug(f"设备ID: '{self.device_info.device_id}'")
        
        if self.device_info.mode == "wireless":
            self.check_wifi_status(self.device_info.device_id)
            
            self.device_info.device_ip = self.get_device_ip(self.device_info.device_id)
            if not self.device_info.device_ip:
                self.die("无法获取设备IP地址，请检查WiFi连接")
            self.log_success(f"获取到设备IP: {self.device_info.device_ip}")
            
            self.enable_tcpip_mode()

    def enable_tcpip_mode(self) -> None:
        """启用TCP/IP模式"""
        if self.device_info.mode != "wireless":
            return

        self.log_step("启用TCP/IP模式...")
        try:
            result = self.run_adb(["-s", self.device_info.device_id, "tcpip", str(self.device_info.port)])
            if not re.search(r"restarting in (tcpip|TCP) mode|already running as (tcpip|TCP)", result.stdout, re.I):
                self.die("无法启动TCP/IP模式")
            
            self.log_success("TCP/IP模式启用成功")
            time.sleep(2)  # 等待ADB重启
        except subprocess.CalledProcessError as e:
            self.die(f"adb tcpip 失败，退出码: {e.returncode}")

    def detect_wireless_device(self) -> bool:
        """检测无线设备"""
        try:
            result = self.run_adb(["devices"])
            for line in result.stdout.splitlines()[1:]:
                if ":" in line and "device" in line:
                    wireless_id = line.split()[0]
                    self.device_info.device_ip = wireless_id.split(":")[0]
                    return True
        except subprocess.CalledProcessError:
            pass
        return False

    def connect_device(self) -> bool:
        """连接设备"""
        retries = 0
        while retries < MAX_RETRIES:
            self.log_step(f"尝试连接设备: {self.device_info.device_ip}:{self.device_info.port} "
                         f"(第 {retries + 1}/{MAX_RETRIES} 次)")
            
            try:
                self.run_adb(["connect", f"{self.device_info.device_ip}:{self.device_info.port}"])
                self.run_adb(["-s", f"{self.device_info.device_ip}:{self.device_info.port}", "shell", "exit"])
                self.log_success("无线连接成功")
                return True
            except subprocess.CalledProcessError:
                self.log_step("获取设备列表:")
                self.run_adb(["devices"])
            
            retries += 1
            if retries < MAX_RETRIES:
                self.log_step(f"尝试 {retries}/{MAX_RETRIES}: 重试连接...")
                time.sleep(RETRY_DELAY)
        
        self.log_error("无法建立无线连接\n"
                      "提示: 无线连接可能因以下原因被中断:\n"
                      " 1. 设备重启\n"
                      " 2. USB调试被禁用\n"
                      " 3. WiFi网络改变\n"
                      " 4. 开发者选项被重置\n"
                      "如遇以上情况，请重新USB连接设备并运行脚本。")
        return False

    def set_rotation(self) -> bool:
        """设置屏幕方向"""
        if self.device_info.rotation is None:
            return True
            
        self.log_step(f"设置屏幕方向: {self.device_info.rotation}")
        try:
            self.run_adb(["shell", "settings put system accelerometer_rotation 0"])
            self.run_adb(["shell", f"settings put system user_rotation {self.device_info.rotation}"])
            self.log_success("方向设置成功")
            return True
        except subprocess.CalledProcessError:
            self.log_error("无法设置屏幕方向")
            return False

    def get_target_device(self) -> str:
        """获取目标设备标识符"""
        if self.device_info.mode == "usb":
            return self.device_info.device_id
        return f"{self.device_info.device_ip}:{self.device_info.port}"

    def start_scrcpy(self) -> None:
        """启动scrcpy"""
        target_device = self.get_target_device()
        scrcpy_opts = ["--turn-screen-off", "--stay-awake"]
        
        self.log_debug(f"使用设备: {target_device}")
        
        # 验证设备连接状态
        try:
            self.run_adb(["-s", target_device, "shell", "echo", "ok"])
        except subprocess.CalledProcessError:
            self.die("设备未连接或状态异常")
        
        # 保存当前设备设置
        self.log_step("保存设备设置...")
        try:
            result = self.run_adb(["-s", target_device, "shell", "settings get global stay_awake"])
            self.device_info.original_stay_awake = result.stdout.strip()
        except subprocess.CalledProcessError:
            self.device_info.original_stay_awake = "0"
            
        try:
            result = self.run_adb(["-s", target_device, "shell", "settings get secure lockscreen.disabled"])
            self.device_info.original_lockscreen = result.stdout.strip()
        except subprocess.CalledProcessError:
            self.device_info.original_lockscreen = "0"
        
        # 在scrcpy期间禁用锁屏，保持唤醒
        self.run_adb(["-s", target_device, "shell", "settings put secure lockscreen.disabled 1"])
        self.run_adb(["-s", target_device, "shell", "settings put global stay_awake 1"])
        
        # 设置屏幕方向
        if self.device_info.rotation is not None and not self.set_rotation():
            self.log_error("屏幕方向设置失败，将使用默认方向")
        
        self.log_step("启动 scrcpy...")
        self.log_debug(f"使用选项: {' '.join(scrcpy_opts)}")
        
        cmd = ["./scrcpy", "-s", target_device] + scrcpy_opts
        try:
            subprocess.run(cmd, check=True)
            self.log_step("正在终止投屏...")
        except subprocess.CalledProcessError as e:
            if e.returncode not in [0, 130, 2]:  # 正常退出|SIGINT|没有设备
                self.log_error(f"scrcpy 异常退出 (错误码: {e.returncode})")

    def connect_to_device(self) -> None:
        """连接设备主函数"""
        if self.device_info.mode == "usb":
            self.log_step("仅使用USB方式投屏")
            self.setup_usb_device()
            return

        # 检查现有无线连接
        if self.detect_wireless_device():
            self.log_step(f"检测到已连接的无线设备: {self.device_info.device_ip}:{self.device_info.port}")
            return
            
        # 尝试使用指定IP连接
        if self.device_info.device_ip:
            if self.connect_device():
                return
        
        # 尝试USB连接并转为无线模式
        self.setup_usb_device()

    def parse_arguments(self) -> None:
        """解析命令行参数"""
        parser = argparse.ArgumentParser(description="scrcpy 无线投屏脚本 (支持方向控制)")
        parser.add_argument("-i", "--ip", help="指定设备 IP (默认: 自动检测或使用上次连接的IP)")
        parser.add_argument("-p", "--port", type=int, default=DEFAULT_PORT, help=f"指定端口 (默认: {DEFAULT_PORT})")
        parser.add_argument("-r", "--rotation", type=int, choices=[0, 1, 3], 
                          help="设置屏幕方向 (0=竖屏, 1=横屏右, 3=横屏左)")
        parser.add_argument("-u", "--usb", action="store_true", help="仅使用USB方式投屏（不启用无线）")
        parser.add_argument("-d", "--debug", action="store_true", help="调试模式")
        
        args = parser.parse_args()
        
        self.debug = args.debug
        self.device_info.device_ip = args.ip or ""
        self.device_info.port = args.port
        self.device_info.rotation = args.rotation
        self.device_info.mode = "usb" if args.usb else "wireless"

    def main(self) -> None:
        """主函数"""
        # 注册信号处理
        signal.signal(signal.SIGINT, lambda sig, frame: self.cleanup())
        signal.signal(signal.SIGTERM, lambda sig, frame: self.cleanup())
        
        try:
            self.parse_arguments()
            self.check_environment()
            
            self.debug = True  # 开启调试模式以查看详细信息
            self.log_debug(f"启动参数: IP={self.device_info.device_ip}, PORT={self.device_info.port}, "
                         f"ROTATION={self.device_info.rotation}, MODE={self.device_info.mode}")
            
            self.connect_to_device()
            self.start_scrcpy()
            
        except Exception as e:
            self.die(f"发生异常: {str(e)}")

if __name__ == "__main__":
    helper = ScrcpyHelper()
    helper.main()
