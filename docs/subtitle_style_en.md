# Subtitle Style Argument

English | [简体中文](./subtitle_style_zh.md)

## Style Setting Examples

Subtitle styles comply with the ASS style specification and can be configured using a comma-separated key-value string. Here's the default configuration:

```bash
Fontname=Arial, Fontsize=13, PrimaryColour=&H00FFFF05, SecondaryColour=&H00FFFFFF, OutlineColour=&H00000000, BackColour=&H00000000, Bold=0, Italic=0, Underline=0, StrikeOut=0, ScaleX=100, ScaleY=100, Spacing=0.5, Angle=0, BorderStyle=1, Outline=0.5, Shadow=0.5, Alignment=2, MarginL=10, MarginR=10, MarginV=10, Encoding=1
```

You can override specific fields as needed, for example:

**Larger font size, bold text and border:**

```bash
--trans_sub_style="Fontsize=18, Bold=1, Outline=2"
```

**Semi-transparent red italic text, aligned to bottom-right:**

```bash
--trans_sub_style="PrimaryColour=&H500000FF, Italic=1, Alignment=3"
```

## Detailed Field Descriptions

| Field Name | Type | Default Value | Description |
| ---------- | ---- | ------------- | ----------- |
| Name | String | "Default" | Style name, case-sensitive, cannot contain commas |
| Fontname | String | "Arial" | Font name, case-sensitive |
| Fontsize | Float | 13 | Font size |
| PrimaryColour | Color | Custom1 | Primary color (typically the text color) |
| SecondaryColour | Color | WHITE | Secondary color (for karaoke, color changes from secondary to primary) |
| OutlineColour | Color | BLACK | Border color |
| BackColour | Color | BLACK | Shadow color |
| Bold | Boolean | False | Bold text |
| Italic | Boolean | False | Italic text |
| Underline | Boolean | False | Underlined text |
| StrikeOut | Boolean | False | Strikethrough text |
| ScaleX | Float | 100 | Horizontal scaling percentage |
| ScaleY | Float | 100 | Vertical scaling percentage |
| Spacing | Float | 0.5 | Character spacing (in pixels) |
| Angle | Float | 0 | Rotation angle. Negative = clockwise. In degrees, supports decimals. Pivot point determined by Alignment |
| BorderStyle | Integer | 1 | Border style: 1=border+shadow, 3=opaque box |
| Outline | Float | 0.5 | Border width (in pixels, supports decimals) |
| Shadow | Float | 0.5 | Shadow depth (in pixels, supports decimals, bottom-right offset) |
| Alignment | Integer | 2 | Alignment: 1-9 corresponding to numpad positions |
| MarginL | Integer | 10 | Left margin (in pixels), ignored for right and center alignment |
| MarginR | Integer | 10 | Right margin (in pixels), ignored for left and center alignment |
| MarginV | Integer | 10 | Top/bottom margin (in pixels), ignored for center alignment |
| Encoding | Integer | 1 | Character encoding: 0=ANSI, 1=Default, 128=Japanese, 134=Simplified Chinese, 136=Traditional Chinese. Usually 1 is fine |

## Color Format Details

Color values use the format `&HAABBGGRR`, which is an 8-digit hexadecimal number where:

- AA: Alpha (transparency), 00 means fully opaque, FF means fully transparent
- BB: Blue component
- GG: Green component
- RR: Red component

Examples:

- `&H00FFFFFF` = Opaque white
- `&H000000FF` = Opaque red
- `&H8000FF00` = Semi-transparent green

## Alignment Details

Alignment values correspond to the following positions (matching numpad layout):

```
7 8 9
4 5 6
1 2 3
```

- 1: Bottom-left
- 2: Bottom-center
- 3: Bottom-right
- 4: Middle-left
- 5: Middle-center
- 6: Middle-right
- 7: Top-left
- 8: Top-center
- 9: Top-right
