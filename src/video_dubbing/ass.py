"""
Copied from https://github.com/nattofriends/python-ass/blob/master/ass/document.py
"""

import itertools
from datetime import timedelta
from pathlib import Path


class Color(object):
    """Represents a color in the ASS format."""

    def __init__(self, r, g, b, a=0):
        """Made up of red, green, blue and alpha components (in that order!)."""
        self.r = r
        self.g = g
        self.b = b
        self.a = a

    def to_int(self):
        return self.a + (self.b << 8) + (self.g << 16) + (self.r << 24)

    def to_ass(self):
        """Convert this color to a Visual Basic (ASS) color code."""
        return "&H{a:02X}{b:02X}{g:02X}{r:02X}".format(**self.__dict__)

    @classmethod
    def from_ass(cls, v):
        """Convert a Visual Basic (ASS) color code into an ``Color``."""
        if not v.startswith("&H"):
            raise ValueError("color must start with &H")

        rest = int(v[2:], 16)

        # AABBGGRR
        r = rest & 0xFF
        rest >>= 8

        g = rest & 0xFF
        rest >>= 8

        b = rest & 0xFF
        rest >>= 8

        a = rest & 0xFF

        return cls(r, g, b, a)

    def __repr__(self):
        return "{name}(r=0x{r:02x}, g=0x{g:02x}, b=0x{b:02x}, a=0x{a:02x})".format(
            name=self.__class__.__name__, r=self.r, g=self.g, b=self.b, a=self.a
        )


WHITE = Color(255, 255, 255)
RED = Color(255, 0, 0)
BLACK = Color(0, 0, 0)
Custom1 = Color(5, 255, 255)


class _Field(object):
    _last_creation_order = -1

    def __init__(self, name, type, default=None):
        self.name = name
        self.type = type
        self.default = default

        _Field._last_creation_order += 1
        self._creation_order = self._last_creation_order

    def __get__(self, obj, type=None):
        if obj is None:
            return self
        return obj.fields.get(self.name, self.default)

    def __set__(self, obj, v):
        obj.fields[self.name] = v

    @staticmethod
    def dump(v):
        if v is None:
            return ""

        if isinstance(v, bool):
            return str(-int(v))

        if isinstance(v, timedelta):
            return _Field.timedelta_to_ass(v)

        if isinstance(v, float):
            return "{0:g}".format(v)

        if hasattr(v, "to_ass"):
            return v.to_ass()

        return str(v)

    def parse(self, v):
        if self.type is None:
            return None

        if self.type is bool:
            return bool(-int(v))

        if self.type is timedelta:
            return _Field.timedelta_from_ass(v)

        if hasattr(self.type, "from_ass"):
            return self.type.from_ass(v)

        return self.type(v)

    @staticmethod
    def timedelta_to_ass(td):
        r = int(td.total_seconds())

        r, secs = divmod(r, 60)
        hours, mins = divmod(r, 60)

        return "{hours:.0f}:{mins:02.0f}:{secs:02.0f}.{csecs:02}".format(
            hours=hours, mins=mins, secs=secs, csecs=td.microseconds // 10000
        )

    @staticmethod
    def timedelta_from_ass(v):
        hours, mins, secs = v.split(":", 2)
        secs, csecs = secs.split(".", 2)

        r = int(hours) * 60 * 60 + int(mins) * 60 + int(secs) + int(csecs) * 1e-2

        return timedelta(seconds=r)


class _WithFieldMeta(type):
    def __new__(cls, name, bases, dct):
        newcls = type.__new__(cls, name, bases, dct)

        field_defs = []
        for base in bases:
            if hasattr(base, "_field_defs"):
                field_defs.extend(base._field_defs)
        field_defs.extend(
            tuple(sorted((f for f in dct.values() if isinstance(f, _Field)), key=lambda f: f._creation_order))
        )
        newcls._field_defs = tuple(field_defs)

        field_mappings = {}
        for base in bases:
            if hasattr(base, "_field_mappings"):
                field_mappings.update(base._field_mappings)
        field_mappings.update({f.name: f for f in field_defs})
        newcls._field_mappings = field_mappings

        newcls.DEFAULT_FIELD_ORDER = tuple(f.name for f in field_defs)
        return newcls


def add_metaclass(metaclass):
    """
    Decorate a class to replace it with a metaclass-constructed version.

    Usage:

    @add_metaclass(MyMeta)
    class MyClass(object):
        ...

    That code produces a class equivalent to

    class MyClass(object, metaclass=MyMeta):
        ...

    on Python 3 or

    class MyClass(object):
        __metaclass__ = MyMeta

    on Python 2

    Requires Python 2.6 or later (for class decoration). For use on Python
    2.5 and earlier, use the legacy syntax:

    class MyClass(object):
        ...
    MyClass = add_metaclass(MyClass)

    Taken from six.py.
    https://bitbucket.org/gutworth/six/src/default/six.py
    """

    def wrapper(cls):
        orig_vars = cls.__dict__.copy()
        orig_vars.pop("__dict__", None)
        orig_vars.pop("__weakref__", None)
        for slots_var in orig_vars.get("__slots__", ()):
            orig_vars.pop(slots_var)
        return metaclass(cls.__name__, cls.__bases__, orig_vars)

    return wrapper


class Tag(object):
    """A tag in ASS, e.g. {\\b1}. Multiple can be used like {\\b1\\i1}."""

    def __init__(self, name: str, params: list[str]):
        self.name = name
        self.params = params

    def to_ass(self):
        if not self.params:
            params = ""
        elif len(self.params) == 1:
            params = self.params[0]
        else:
            params = "(" + ",".join(_Field.dump(param) for param in self.params) + ")"

        return "\\{name}{params}".format(name=self.name, params=params)

    @staticmethod
    def strip_tags(parts, keep_drawing_commands=False):
        text_parts = []

        it = iter(parts)

        for part in it:
            if isinstance(part, Tag):
                # if we encounter a \p1 tag, skip everything until we get to
                # \p0
                if not keep_drawing_commands and part.name == "p" and part.params == [1]:
                    for part2 in it:
                        if isinstance(part2, Tag) and part2.name == "p" and part2.params == [0]:
                            break
            else:
                text_parts.append(part)

        return "".join(text_parts)

    @classmethod
    def from_ass(cls, s):
        raise NotImplementedError


@add_metaclass(_WithFieldMeta)
class ASS(object):
    """An ASS document."""

    SCRIPT_INFO_HEADER = "[Script Info]"
    STYLE_SSA_HEADER = "[V4 Styles]"
    STYLE_ASS_HEADER = "[V4+ Styles]"
    EVENTS_HEADER = "[Events]"

    FORMAT_TYPE = "Format"

    VERSION_ASS = "v4.00+"
    VERSION_SSA = "v4.00"

    script_type = _Field("ScriptType", str, default=VERSION_ASS)
    play_res_x = _Field("PlayResX", int, default=640)
    play_res_y = _Field("PlayResY", int, default=480)
    wrap_style = _Field("WrapStyle", int, default=0)
    scaled_border_and_shadow = _Field("ScaledBorderAndShadow", str, default="yes")

    def __init__(self):
        """Create an empty ASS document."""
        self.fields = {}

        self.styles: list[Style] = []
        self.styles_field_order = Style.DEFAULT_FIELD_ORDER

        self.events: list[_Event] = []
        self.events_field_order = _Event.DEFAULT_FIELD_ORDER

    def add_or_update_style(self, kv_string: str, name: str = "Default"):
        """
        更新或创建格式.

        Args:
            kv_string: 逗号分隔的键值对字符串. 如 "Fontsize=9, Bold=1"
            name: Style 的名称, 若不存在则新建
        """
        # 解析键值对字符串
        pairs = {}
        for pair in kv_string.split(","):
            if "=" not in pair:
                continue
            key, value = pair.split("=", 1)
            pairs[key.strip()] = value.strip()
        # ignore Name in kv_string
        pairs["Name"] = name

        # 查找是否已存在该名称的Style
        style = Style()
        exist = False
        for s in self.styles:
            if s.name == name:
                exist = True
                style = s
                break

        for key, value in pairs.items():
            if key in Style._field_mappings:
                field: _Field = Style._field_mappings[key]
                parsed_value = field.parse(value)
                style.fields[key] = parsed_value
        if not exist:
            self.styles.append(style)
        return style

    @classmethod
    def from_file(cls, path: str | Path):
        doc = cls()
        with open(path, encoding="utf-8") as f:
            lines = iter(
                [
                    (i, line)
                    for i, line in ((i, line.rstrip("\r\n")) for i, line in enumerate(f))
                    if line and line[0] != ";"
                ]
            )

        # [Script Info]
        for i, line in lines:
            if i == 0 and line[:3] == "\xef\xbb\xbf":
                line = line[3:]

            if i == 0 and line[0] == "\ufeff":
                line = line.strip("\ufeff")

            if line.lower() == ASS.SCRIPT_INFO_HEADER.lower():
                break

            raise ValueError("expected script info header")

        # field_name: field
        for i, line in lines:
            if (
                doc.script_type.lower() == doc.VERSION_ASS.lower() and line.lower() == ASS.STYLE_ASS_HEADER.lower()
            ) or (doc.script_type.lower() == doc.VERSION_SSA.lower() and line.lower() == ASS.STYLE_SSA_HEADER.lower()):
                break

            field_name, field = line.split(":", 1)
            field = field.lstrip()

            if field_name in ASS._field_mappings:
                field = ASS._field_mappings[field_name].parse(field)

            doc.fields[field_name] = field

        # [V4 Styles]
        i, line = next(lines)

        type_name, line = line.split(":", 1)
        line = line.lstrip()

        # Format: ...
        if type_name.lower() != ASS.FORMAT_TYPE.lower():
            raise ValueError("expected format line in styles")

        field_order = [x.strip() for x in line.split(",")]
        doc.styles_field_order = field_order

        # Style: ...
        for i, line in lines:
            if line.lower() == ASS.EVENTS_HEADER.lower():
                break

            type_name, line = line.split(":", 1)
            line = line.lstrip()

            if type_name.lower() != Style.TYPE.lower():
                raise ValueError("expected style line in styles")

            doc.styles.append(Style.parse(line, field_order))

        # [Events]
        i, line = next(lines)

        type_name, line = line.split(":", 1)
        line = line.lstrip()

        # Format: ...
        if type_name.lower() != ASS.FORMAT_TYPE.lower():
            raise ValueError("expected format line in events")

        field_order = [x.strip() for x in line.split(",")]
        doc.events_field_order = field_order

        # Dialogue: ...
        # Comment: ...
        # etc.
        for i, line in lines:
            type_name, line = line.split(":", 1)
            line = line.lstrip()

            doc.events.append(
                (
                    {
                        "Dialogue": Dialogue,
                        "Comment": Comment,
                        "Picture": Picture,
                        "Sound": Sound,
                        "Movie": Movie,
                        "Command": Command,
                    }
                )[type_name].parse(line, field_order)
            )

        return doc

    def save(self, path: str | Path):
        with open(path, mode="w", encoding="utf-8") as f:
            f.write(ASS.SCRIPT_INFO_HEADER + "\n")
            for k in itertools.chain(
                (field for field in self.DEFAULT_FIELD_ORDER if field in self.fields),
                (field for field in self.fields if field not in self._field_mappings),
            ):
                f.write(k + ": " + _Field.dump(self.fields[k]) + "\n")
            f.write("\n")

            f.write(ASS.STYLE_ASS_HEADER + "\n")
            f.write(ASS.FORMAT_TYPE + ": " + ", ".join(self.styles_field_order) + "\n")
            for style in self.styles:
                f.write(style.dump_with_type(self.styles_field_order) + "\n")
            f.write("\n")

            f.write(ASS.EVENTS_HEADER + "\n")
            f.write(ASS.FORMAT_TYPE + ": " + ", ".join(self.events_field_order) + "\n")
            for event in self.events:
                f.write(event.dump_with_type(self.events_field_order) + "\n")
            f.write("\n")

    def apply_style(self, style_name: str, placeholder: str = "<new-style>"):
        """
        在 ass 文本中插入控制符以应用指定样式.

        Args:
            style_name: 要使用的样式名称. 此函数不检查其是否存在.
            placeholder: 在字幕文本中用于指代当前格式的占位符.
        """
        for e in self.events:
            e.text = e.text.replace(placeholder, f"{{\\r{style_name}}}")


@add_metaclass(_WithFieldMeta)
class _Line(object):
    def __init__(self, *args, **kwargs):
        self.fields = {f.name: f.default for f in self._field_defs}

        for k, v in zip(self.DEFAULT_FIELD_ORDER, args):
            self.fields[k] = v

        for k, v in kwargs.items():
            if hasattr(self, k):
                setattr(self, k, v)
            else:
                self.fields[k] = v

    def dump(self, field_order=None):
        """Dump an ASS line into text format. Has an optional field order
        parameter in case you have some wonky format.
        """
        if field_order is None:
            field_order = self.DEFAULT_FIELD_ORDER

        return ",".join(_Field.dump(self.fields[field]) for field in field_order)

    def dump_with_type(self, field_order=None):
        """Dump an ASS line into text format, with its type prepended."""
        return self.TYPE + ": " + self.dump(field_order)

    @classmethod
    def parse(cls, line: str, field_order: list[str] | None = None):
        """Parse an ASS line from text format. Has an optional field order
        parameter in case you have some wonky format.
        """
        if field_order is None:
            field_order = cls.DEFAULT_FIELD_ORDER

        parts = line.split(",", len(field_order) - 1)

        if len(parts) != len(field_order):
            raise ValueError("arity of line does not match arity of field order")

        fields = {}

        for field_name, field in zip(field_order, parts):
            if field_name in cls._field_mappings:
                field = cls._field_mappings[field_name].parse(field)
            fields[field_name] = field

        return cls(**fields)


class Style(_Line):
    """A style line in ASS."""

    TYPE = "Style"

    name = _Field("Name", str, default="Default")  # 样式名称, 区分大小写, 不能包含逗号
    fontname = _Field("Fontname", str, default="Arial")  # 字体名称, 区分大小写
    fontsize = _Field("Fontsize", float, default=13)  # 字体大小
    primary_color = _Field("PrimaryColour", Color, default=Custom1)  # 主体颜色（一般情况下文字的颜色）
    secondary_color = _Field("SecondaryColour", Color, default=WHITE)  # 次要颜色（卡拉OK效果中颜色由次要变为主体）
    outline_color = _Field("OutlineColour", Color, default=BLACK)  # 边框颜色
    back_color = _Field("BackColour", Color, default=BLACK)  # 阴影颜色
    bold = _Field("Bold", bool, default=False)  # 粗体
    italic = _Field("Italic", bool, default=False)  # 斜体
    underline = _Field("Underline", bool, default=False)  # 下划线
    strike_out = _Field("StrikeOut", bool, default=False)  # 删除线
    scale_x = _Field("ScaleX", float, default=100)  # 水平缩放百分比
    scale_y = _Field("ScaleY", float, default=100)  # 垂直缩放百分比
    spacing = _Field("Spacing", float, default=0.5)  # 字符间距 (像素)
    angle = _Field("Angle", float, default=0)  # 旋转角度. 负数=顺时针旋转. 单位度, 支持小数. 基点由 Alignment 决定
    border_style = _Field("BorderStyle", int, default=1)  # 边框样式：1=边框+阴影, 3=不透明底框
    outline = _Field("Outline", float, default=0.5)  # 边框宽度（单位像素，可用小数）
    shadow = _Field("Shadow", float, default=0.5)  # 阴影深度（单位像素，可用小数，右下偏移）
    alignment = _Field("Alignment", int, default=2)  # 对齐方式: 1-9 对应小键盘数字方位
    margin_l = _Field("MarginL", int, default=10)  # 左边距（像素） 右对齐和中对齐时无效
    margin_r = _Field("MarginR", int, default=10)  # 右边距（像素） 左对齐和中对齐时无效
    margin_v = _Field("MarginV", int, default=10)  # 上/下边距（像素） 中对齐时无效
    # 字符编码：0=ANSI, 1=Default, 128=日文, 134=简中, 136=繁中 一般用默认1即可
    encoding = _Field("Encoding", int, default=1)

    @classmethod
    def get_default_kv_string(cls) -> str:
        """
        获取默认值对应的kv_string
        """
        fields = []
        for field in cls._field_defs:
            if field.name == "Name":
                continue
            value = _Field.dump(field.default)
            fields.append(f"{field.name}={value}")
        return ",".join(fields)


class _Event(_Line):
    layer = _Field("Layer", int, default=0)
    start = _Field("Start", timedelta, default=timedelta(0))
    end = _Field("End", timedelta, default=timedelta(0))
    style = _Field("Style", str, default="Default")
    name = _Field("Name", str, default="")
    margin_l = _Field("MarginL", int, default=0)
    margin_r = _Field("MarginR", int, default=0)
    margin_v = _Field("MarginV", int, default=0)
    effect = _Field("Effect", str, default="")
    text = _Field("Text", str, default="")


class Dialogue(_Event):
    """A dialog event."""

    TYPE = "Dialogue"


class Comment(_Event):
    """A comment event."""

    TYPE = "Comment"


class Picture(_Event):
    """A picture event. Not widely supported."""

    TYPE = "Picture"


class Sound(_Event):
    """A sound event. Not widely supported."""

    TYPE = "Sound"


class Movie(_Event):
    """A movie event. Not widely supported."""

    TYPE = "Movie"


class Command(_Event):
    """A command event. Not widely supported."""

    TYPE = "Command"
