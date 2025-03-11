import unittest

from video_dubbing.ass import ASS, Color, Style


class TestASS(unittest.TestCase):
    def setUp(self):
        self.ass = ASS()
        # Add a default style to test updates
        self.default_style = Style(name="Default", fontsize=20, bold=False)
        self.ass.styles.append(self.default_style)

    def test_add_new_style(self):
        # Test adding a completely new style
        new_style = self.ass.add_or_update_style("Fontsize=25, Bold=1", name="NewStyle")

        self.assertEqual(len(self.ass.styles), 2)
        self.assertEqual(new_style.name, "NewStyle")
        self.assertEqual(new_style.fontsize, 25.0)
        self.assertEqual(new_style.bold, True)

    def test_update_existing_style(self):
        # Test updating an existing style
        updated_style = self.ass.add_or_update_style("Fontsize=30, Italic=1,PrimaryColour=&HFFCC00", name="Default")

        # Should still have only one style
        self.assertEqual(len(self.ass.styles), 1)
        # Should be the same object
        self.assertIs(updated_style, self.default_style)
        # Check updated values
        self.assertEqual(updated_style.fontsize, 30.0)
        self.assertEqual(updated_style.italic, True)
        self.assertIsInstance(updated_style.primary_color, Color)
        self.assertEqual(updated_style.primary_color.r, 0)
        self.assertEqual(updated_style.primary_color.g, 0xCC)
        self.assertEqual(updated_style.primary_color.b, 0xFF)
        # Original values that weren't updated should remain
        self.assertEqual(updated_style.bold, False)

    def test_add_with_multiple_fields(self):
        # Test adding a style with multiple fields
        new_style = self.ass.add_or_update_style(
            "Fontname=Arial, Fontsize=18, Bold=1, Italic=-1, Underline=1, ScaleX=120", name="ComplexStyle"
        )

        self.assertEqual(new_style.fontname, "Arial")
        self.assertEqual(new_style.fontsize, 18.0)
        self.assertEqual(new_style.bold, True)
        self.assertEqual(new_style.italic, True)
        self.assertEqual(new_style.underline, True)
        self.assertEqual(new_style.scale_x, 120.0)

    def test_ignore_invalid_fields(self):
        # Test that invalid field names are ignored
        original_style = self.default_style
        updated_style = self.ass.add_or_update_style("InvalidField=Value, Fontsize=15", name="Default")

        # Should update valid fields
        self.assertEqual(updated_style.fontsize, 15.0)
        # Should be the same object
        self.assertIs(updated_style, original_style)

    def test_ignore_invalid_format(self):
        # Test handling of malformed input
        original_style = self.default_style
        updated_style = self.ass.add_or_update_style("InvalidFormat, Fontsize=15", name="Default")

        # Should still update valid parts
        self.assertEqual(updated_style.fontsize, 15.0)
        # Should be the same object
        self.assertIs(updated_style, original_style)

    def test_default_kv_string(self):
        d = Style.get_default_kv_string()
        self.ass.add_or_update_style(d)
        self.assertEqual(self.ass.styles[0].dump(), Style().dump())


if __name__ == "__main__":
    unittest.main()
