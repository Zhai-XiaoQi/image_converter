# 图片格式转换工具 1.0

一个面向素材处理场景的 Windows 桌面工具，支持批量图片格式转换、目录树勾选预览、单图裁剪编辑，以及 EXE 打包分享。

## 主要功能

- 批量输入：选择文件夹或多个图片文件。
- 支持输入格式：JPG、JPEG、PNG、WEBP、BMP、TIFF。
- 支持输出格式：JPG、PNG、WEBP。
- 批量筛选：按 JPG / PNG / WEBP / 其他格式筛选。
- 模糊搜索：按文件名或相对路径搜索图片。
- 目录树选择：左侧勾选什么，右侧预览就显示什么。
- 保留目录结构：转换后可保持原始文件夹层级。
- 单图处理：裁剪、缩放、旋转、比例预设、吸附、撤销/重做、保存副本。
- 打包发布：可用 PyInstaller 打包成 EXE，分享给没有 Python 环境的用户。

## 运行脚本版

推荐双击：

```text
启动图片格式转换工具_无黑窗.vbs
```

备用入口：

```text
启动图片格式转换工具.bat
```

如果直接运行 Python：

```powershell
python image_converter_gui.py
```

## 打包 EXE

项目已验证可用 PyInstaller 打包：

```powershell
python -m PyInstaller --noconsole --name 图片格式转换工具 --distpath dist --workpath build --specpath . image_converter_gui.py
```

打包后会生成：

```text
dist/
└─ 图片格式转换工具/
   ├─ 图片格式转换工具.exe
   └─ _internal/
```

分享给别人时，请发送整个 `图片格式转换工具` 文件夹，或压缩成 zip 后发送。不要只单独发送 `.exe`，因为 `_internal` 是运行依赖。

## 注意事项

- `仅 JPG 渐进式` 只对 JPG/JPEG 输出有效，默认不勾选。
- 转换重要素材时，首次使用不建议勾选“成功后删除原图”。
- 输出目录建议放在输入目录旁边，避免输出结果被再次扫描。
- 单图编辑默认保存副本，覆盖原图前会二次确认。

## 开发知识库

项目开发过程、技术栈说明、踩坑复盘和可复用模板见：

```text
图片格式转换工具_1.0_开发知识库.html
```
