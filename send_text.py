#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
发送文本到ADB设备脚本

功能说明：
1. 直接发送文本到设备（支持中文）
2. 无需切换输入法

使用方法：
    ./send_text_to_adb.py "要发送的文本"
    ./send_text_to_adb.py -d "要发送的文本"  # 启用调试模式

"""

import argparse
import os
import subprocess
import sys
from pathlib import Path

class Colors:
    INFO = "\033[1;34m"     # 蓝色
    SUCCESS = "\033[1;32m"  # 绿色
    ERROR = "\033[1;31m"    # 红色
    RESET = "\033[0m"

class AdbTextSender:
    def __init__(self):
        self.script_dir = Path(__file__).parent.absolute()
        os.chdir(self.script_dir)
        
    def log_step(self, message: str) -> None:
        print(f"{Colors.INFO}==> {message}{Colors.RESET}")

    def log_success(self, message: str) -> None:
        print(f"{Colors.SUCCESS}[SUCCESS] {message}{Colors.RESET}")

    def log_error(self, message: str) -> None:
        print(f"{Colors.ERROR}[ERROR] {message}{Colors.RESET}", file=sys.stderr)

    def log_debug(self, message: str) -> None:
        """调试日志"""
        if hasattr(self, 'debug') and self.debug:
            print(f"[DEBUG] {message}")

    def run_adb(self, args: list, check: bool = True, capture_output: bool = True) -> subprocess.CompletedProcess:
        """运行adb命令"""
        cmd = ["./adb"] + args
        self.log_debug(f"执行命令: {' '.join(cmd)}")
        try:
            result = subprocess.run(cmd, check=check, capture_output=capture_output, text=True, encoding="utf-8")
            return result
        except subprocess.CalledProcessError as e:
            if check:
                self.log_error(f"ADB命令执行失败: {' '.join(cmd)}")
                self.log_error(f"错误信息: {e.stderr}")
                raise
            return e
        except UnicodeDecodeError:
            # 尝试使用其他编码
            result = subprocess.run(cmd, check=check, capture_output=capture_output, text=True, encoding="gbk")
            return result

    def send_text(self, text: str) -> None:
        """发送文本到设备"""
        self.log_step(f"发送文本: {text}...")
        
        # 使用adbkeyboard专用的广播命令发送文本
        # 正确格式：am broadcast -a ADB_INPUT_TEXT --es msg "文本内容"
        result = self.run_adb(["shell", "am", "broadcast", "-a", "ADB_INPUT_TEXT", "--es", "msg", text])
        self.log_debug(f"广播命令结果: {result.stdout}")
        self.log_success("文本发送成功")

    def main(self) -> None:
        """主函数"""
        parser = argparse.ArgumentParser(description="发送文本到ADB设备")
        parser.add_argument("text", help="要发送的文本")
        parser.add_argument("-d", "--debug", action="store_true", help="启用调试模式")
        args = parser.parse_args()

        self.debug = args.debug

        # 检查adb是否存在
        if not Path("./adb").is_file():
            self.log_error("未找到adb文件，请确保adb位于脚本同一目录下")
            sys.exit(1)

        # 检查设备连接
        result = self.run_adb(["devices"], capture_output=True)
        devices = [line.split()[0] for line in result.stdout.splitlines()[1:] if line.strip()]
        if not devices:
            self.log_error("未检测到任何连接的设备")
            sys.exit(1)
        if len(devices) > 1:
            self.log_error("检测到多个设备，请确保只有一个设备连接")
            sys.exit(1)

        try:
            # 直接发送文本，不切换输入法
            self.send_text(args.text)
            
        except Exception as e:
            self.log_error(f"发生错误: {str(e)}")
            sys.exit(1)

if __name__ == "__main__":
    sender = AdbTextSender()
    sender.main()
