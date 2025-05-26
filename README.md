# Scrcpy Wireless Connect Script

一个用于帮助快速建立 scrcpy 无线调试连接的 Shell 脚本。支持自动检测设备、USB/无线连接、屏幕旋转等功能。

## 功能特点

- 支持 USB 和无线两种连接方式
- 自动检测并连接已配对的无线设备
- 支持屏幕方向控制（竖屏/横屏）
- 智能的设备状态管理
- 完善的错误处理和调试信息

## 使用方法

```bash
./wireless_connect.sh [-i IP] [-p PORT] [-r 0|1|3] [-h] [-d]

选项:
 -i IP    指定设备 IP (默认: 自动检测或使用上次连接的IP)
 -p PORT  指定端口 (默认: 5555)
 -r ROT   设置屏幕方向 (0=竖屏, 1=横屏右, 3=横屏左)
 -d       启用调试模式
 -h       显示帮助信息

示例:
# 横屏模式连接指定IP的设备
./wireless_connect.sh -i 192.168.1.100 -r 1

# 竖屏模式连接自动检测的设备
./wireless_connect.sh -r 0
```

## 依赖要求

- adb (Android Debug Bridge)
- scrcpy
- bash 4.0+

## 使用说明

1. 首次使用时，将手机通过 USB 连接到电脑
2. 确保手机已启用 USB 调试模式
3. 运行脚本，它会自动配置无线连接
4. 配置成功后，可以拔掉 USB 线，使用无线连接

## 注意事项

- 手机需要开启 USB 调试和无线调试
- 手机和电脑需要在同一个 WiFi 网络中
- 部分功能可能需要 root 权限
