"""Keep UI emoji out of speech engines that pronounce their accessibility names."""

import re

PICTOGRAPHS = re.compile(
    '[\U0001f000-\U0001faff\u2600-\u27bf\u231a\u231b'
    '\u23e9-\u23f3\u23f8-\u23fa\u25aa\u25ab\u25b6\u25c0\u25fb-\u25fe]'
)
PRESENTATION = re.compile('[\ufe0e\ufe0f\u200d\u20e3\U000e0020-\U000e007f]')

__all__ = ["spoken_text"]


def spoken_text(text: str) -> str:
    """Strip emoji and variation selectors, then collapse the leftover spacing.

    Emoji are replaced by a space (not deleted) so that ``"你好！😊"`` does not
    become ``"你好！"`` glued to the following word. Text content is otherwise
    untouched: Chinese, digits, currency and degree signs all survive.
    """
    text = PICTOGRAPHS.sub(' ', text)
    text = PRESENTATION.sub('', text)
    return re.sub(r'[ \t]+', ' ', text).strip()
