import re

def test_superscript_pattern():
    s = "Example<sup>1</sup>"
    assert re.search(r"<sup>\d+</sup>", s)
