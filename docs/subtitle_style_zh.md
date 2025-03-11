# 字幕样式参数说明

简体中文 | [English](./subtitle_style_en.md)

## 样式设置示例

字幕样式符合 ASS 样式规范, 可使用逗号分隔的键值字符串进行配置. 以下是默认配置的表示:

```bash
Fontname=Arial, Fontsize=13, PrimaryColour=&H00FFFF05, SecondaryColour=&H00FFFFFF, OutlineColour=&H00000000, BackColour=&H00000000, Bold=0, Italic=0, Underline=0, StrikeOut=0, ScaleX=100, ScaleY=100, Spacing=0.5, Angle=0, BorderStyle=1, Outline=0.5, Shadow=0.5, Alignment=2, MarginL=10, MarginR=10, MarginV=10, Encoding=1
```

可以根据需要覆盖部分字段, 例如:

**放大字号, 加粗文字和边框：**

```bash
--trans_sub_style="Fontsize=18, Bold=1, Outline=2"
```

**半透明红色斜体文字，右下对齐：**

```bash
--trans_sub_style="PrimaryColour=&H500000FF, Italic=1, Alignment=3"
```

## 各字段详细说明

| 字段名 | 类型 | 默认值 | 说明 |
| ----- | ---- | ----- | ---- |
| Name | 字符串 | "Default" | 样式名称，区分大小写，不能包含逗号 |
| Fontname | 字符串 | "Arial" | 字体名称，区分大小写 |
| Fontsize | 浮点数 | 13 | 字体大小 |
| PrimaryColour | 颜色 | Custom1 | 主体颜色（一般情况下文字的颜色） |
| SecondaryColour | 颜色 | WHITE | 次要颜色（卡拉OK效果中颜色由次要变为主体） |
| OutlineColour | 颜色 | BLACK | 边框颜色 |
| BackColour | 颜色 | BLACK | 阴影颜色 |
| Bold | 布尔值 | False | 粗体 |
| Italic | 布尔值 | False | 斜体 |
| Underline | 布尔值 | False | 下划线 |
| StrikeOut | 布尔值 | False | 删除线 |
| ScaleX | 浮点数 | 100 | 水平缩放百分比 |
| ScaleY | 浮点数 | 100 | 垂直缩放百分比 |
| Spacing | 浮点数 | 0.5 | 字符间距 (像素) |
| Angle | 浮点数 | 0 | 旋转角度。负数=顺时针旋转。单位度，支持小数。基点由 Alignment 决定 |
| BorderStyle | 整数 | 1 | 边框样式：1=边框+阴影, 3=不透明底框 |
| Outline | 浮点数 | 0.5 | 边框宽度（单位像素，可用小数） |
| Shadow | 浮点数 | 0.5 | 阴影深度（单位像素，可用小数，右下偏移） |
| Alignment | 整数 | 2 | 对齐方式: 1-9 对应小键盘数字方位 |
| MarginL | 整数 | 10 | 左边距（像素）右对齐和中对齐时无效 |
| MarginR | 整数 | 10 | 右边距（像素）左对齐和中对齐时无效 |
| MarginV | 整数 | 10 | 上/下边距（像素）中对齐时无效 |
| Encoding | 整数 | 1 | 字符编码：0=ANSI, 1=Default, 128=日文, 134=简中, 136=繁中 一般用默认1即可 |

## 颜色格式说明

颜色字段的值格式为 `&HAABBGGRR`，是一个8位16进制数，表示方式为：

- AA：透明度（Alpha），00表示完全不透明，FF表示完全透明
- BB：蓝色（Blue）分量
- GG：绿色（Green）分量
- RR：红色（Red）分量

例如：

- `&H00FFFFFF` = 不透明白色
- `&H000000FF` = 不透明红色
- `&H8000FF00` = 半透明绿色

## 对齐方式说明

Alignment 数值对应的位置如下（对应小键盘数字）：

```
7 8 9
4 5 6
1 2 3
```

- 1: 左下
- 2: 居中下
- 3: 右下
- 4: 左中
- 5: 居中中
- 6: 右中
- 7: 左上
- 8: 居中上
- 9: 右上
