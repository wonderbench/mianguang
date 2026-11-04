# V0.2.0 编译产物

对象：XIAO ESP32C3，4 MB Flash，C1001 雷达接口载板。已编译及离线镜像校验，**未烧录、未实机验证**。接线、供电和启动确认命令见 `firmware/README.md`。

| 文件 | 用途 / 写入偏移 |
|---|---|
| `mianguang_v0.2.0_full.bin` | 包含下述四段的完整镜像，起始偏移 `0x0` |
| `bootloader.bin` | 引导程序，`0x0` |
| `partitions.bin` | 已验证的分区表，`0x8000` |
| `boot_app0.bin` | Arduino OTA初始数据，`0xe000` |
| `firmware.bin` | 应用程序，`0x10000`；不能当作从 `0x0` 开始的完整镜像 |
| `firmware.elf` | 带符号的链接产物，供调试和故障定位 |
| `manifest.json` | 构建版本、内存占用、源码及产物SHA-256 |

完整镜像的布局从实际构建的分区表和该版本 Arduino 构建脚本核对，保留原有各镜像的 Flash 头配置。推荐依照源码工程用 PlatformIO 上传，工具会使用相应偏移；不要在电源路径尚未检查时直接给载板双路供电。

确认供电后需发送 `radar on`，再按实际安装和光学检查情况发送 `install yes` 与 `ambient yes`。默认不自动把串口引脚拉高，不默认确认安装，也不把缺失照度传感器当作黑夜。每次重启确认均清除。
